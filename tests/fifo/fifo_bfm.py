"""Shared helpers for the asynchronous FIFO tests: two unrelated clocks, a writer, a reader and a scoreboard.

Inputs are driven on the FALLING edge of each clock and outputs are sampled on the falling edge, which is half a period after the circuit last
changed them and half a period before it next looks at its inputs. A word counts as written when w_en is 1 while w_full is 0 at that moment,
and as read when r_en is 1 while r_empty is 0, which is exactly the condition under which the circuit acts on the next rising edge.
"""
import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, Timer

DATA_WIDTH = int(os.environ.get("DATA_WIDTH", "8"))
ADDR_WIDTH = int(os.environ.get("ADDR_WIDTH", "3"))
DEPTH = 1 << ADDR_WIDTH
WPERIOD = int(os.environ.get("WPERIOD", "10"))        # ns
RPERIOD = int(os.environ.get("RPERIOD", "10"))        # ns
RPHASE = int(os.environ.get("RPHASE", "3"))           # ns: the read clock starts this long after the write clock
MASK = (1 << DATA_WIDTH) - 1
SLOW = max(WPERIOD, RPERIOD)


def word_number(n):
    """The n-th word the writer sends: n * 37 + 11 (an odd multiplier), so consecutive words always differ and no word repeats within 2**DATA_WIDTH words."""
    return (n * 37 + 11) & MASK


async def start_clocks(dut):
    dut.w_en.value = 0
    dut.r_en.value = 0
    dut.w_data.value = 0
    dut.wrst.value = 0
    dut.rrst.value = 0
    cocotb.start_soon(Clock(dut.wclk, WPERIOD, unit="ns").start())

    async def late_read_clock():
        if RPHASE > 0:                                    # phase 0: both clocks start at the same instant
            await Timer(RPHASE, unit="ns")
        await Clock(dut.rclk, RPERIOD, unit="ns").start()
    cocotb.start_soon(late_read_clock())


async def reset_both(dut):
    """Reset both clock domains together for six periods of the slower clock, release them together, and wait six periods more."""
    dut.w_en.value = 0
    dut.r_en.value = 0
    dut.wrst.value = 1
    dut.rrst.value = 1
    await Timer(6 * SLOW, unit="ns")
    dut.wrst.value = 0
    dut.rrst.value = 0
    await Timer(6 * SLOW, unit="ns")


async def wait_cycles(n):
    """n periods of the slower clock (the fixed unit used for waiting in the tests)."""
    await Timer(n * SLOW, unit="ns")


class Bench:
    """A writer, a reader and a scoreboard running on the two clocks.

    `expected` holds the words the circuit has accepted and not yet given back, oldest first. Every check that can fail is an assertion in the
    coroutines, so the test fails at the moment the circuit misbehaves. Coverage flags record that the traffic really did reach the
    interesting situations."""

    def __init__(self, dut, seed=1, p_write=0.5, p_read=0.5):
        self.dut = dut
        self.rng = random.Random(seed)
        self.p_write, self.p_read = p_write, p_read
        self.write_on = self.read_on = True
        self.expected = []
        self.written = self.read = 0
        self.saw_full = self.saw_empty_with_data = self.saw_write_while_full = self.saw_read_while_empty = False
        self._tasks = [cocotb.start_soon(self._writer()), cocotb.start_soon(self._reader())]

    def stop(self):
        for t in self._tasks:
            t.cancel()

    async def _writer(self):
        d = self.dut
        while True:
            await FallingEdge(d.wclk)
            full = int(d.w_full.value)
            ask = self.write_on and self.rng.random() < self.p_write
            d.w_en.value = int(ask)
            d.w_data.value = word_number(self.written)
            if full:
                self.saw_full = True
                self.saw_write_while_full |= ask
            if ask and not full:
                self.expected.append(word_number(self.written))
                self.written += 1
                assert len(self.expected) <= DEPTH, f"a write was accepted although the FIFO already held {DEPTH} words (overflow): w_full was low"

    async def _reader(self):
        d = self.dut
        while True:
            await FallingEdge(d.rclk)
            empty = int(d.r_empty.value)
            if not empty:
                assert self.expected, "r_empty is low although the FIFO holds no word (underflow)"
                got = int(d.r_data.value)
                assert got == self.expected[0], f"r_data shows {got:#x} but the oldest word is {self.expected[0]:#x}"
            else:
                self.saw_empty_with_data |= bool(self.expected)
            ask = self.read_on and self.rng.random() < self.p_read
            d.r_en.value = int(ask)
            if ask and empty:
                self.saw_read_while_empty = True
            if ask and not empty:
                self.expected.pop(0)
                self.read += 1


async def settle_and_check_flags(dut, bench):
    """Stop all traffic, wait for the flags to catch up, and check they are exact: empty exactly when nothing is stored, full exactly when DEPTH words are."""
    bench.write_on = bench.read_on = False
    await wait_cycles(8)
    stored = len(bench.expected)
    assert int(dut.r_empty.value) == (1 if stored == 0 else 0), f"after settling, r_empty = {int(dut.r_empty.value)} with {stored} words stored"
    assert int(dut.w_full.value) == (1 if stored == DEPTH else 0), f"after settling, w_full = {int(dut.w_full.value)} with {stored} of {DEPTH} words stored"
