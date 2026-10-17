"""Shared helpers for the UART tests: a clock, bit-banged serial frames and monitors.

The same code drives the Verilog and the VHDL circuit. Convention used everywhere: inputs are driven right after a rising
clock edge (so the circuit sees them at the next edge) and outputs are sampled on the falling edge (when they have settled).
"""
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

CLKS = int(os.environ.get("CLKS_PER_BIT", "16"))      # clock cycles per bit, set by the runner for the circuit under test


def frame_bits(byte, stop=1):
    """The bits of one 8N1 frame in transmission order: start (0), eight data bits least-significant first, stop."""
    return [0] + [(byte >> i) & 1 for i in range(8)] + [stop]


async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())


async def reset(dut, cycles=3):
    """Hold the synchronous reset for a few cycles, then release it (leaves us just after a rising edge)."""
    dut.rst.value = 1
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def cycles(dut, n):
    for _ in range(n):
        await RisingEdge(dut.clk)


async def drive_bits(dut, bits, bit_clks):
    """Put bits on rxd, each lasting exactly bit_clks clock cycles. Call it just after a rising edge."""
    for b in bits:
        dut.rxd.value = b
        await cycles(dut, bit_clks)


async def send_frame(dut, byte, bit_clks=None, stop=1):
    await drive_bits(dut, frame_bits(byte, stop), CLKS if bit_clks is None else bit_clks)


class RxMonitor:
    """Watches rx_valid / rx_data / rx_error on every falling edge and remembers when they were high."""

    def __init__(self, dut):
        self.dut = dut
        self.cycle = 0
        self.valid = []          # (cycle, byte) for every cycle in which rx_valid was high
        self.errors = []         # cycle for every cycle in which rx_error was high
        self._task = cocotb.start_soon(self._run())

    async def _run(self):
        while True:
            await FallingEdge(self.dut.clk)
            self.cycle += 1
            if int(self.dut.rx_valid.value) == 1:
                self.valid.append((self.cycle, int(self.dut.rx_data.value)))
            if int(self.dut.rx_error.value) == 1:
                self.errors.append(self.cycle)

    def bytes(self):
        return [b for _, b in self.valid]

    def stop(self):
        self._task.cancel()
