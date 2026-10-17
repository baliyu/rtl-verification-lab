"""Shared helpers for the SPI tests: an SPI slave built from the standard table of the four modes, and a waveform recorder.

Conventions are the same as for the UART tests: inputs are driven right after a rising clock edge, outputs are sampled on the falling edge.
The slave does NOT use the circuit's way of thinking (leading and trailing edges): it uses the published table of the four SPI modes,
which says on which edge (rising or falling) a device samples mosi and on which edge it changes miso.
"""
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

H = int(os.environ.get("CLKS_PER_HALF", "4"))        # system clocks per half sclk period, set by the runner
W = int(os.environ.get("WIDTH", "8"))                # bits per transfer

# (cpol, cpha) -> (edge on which a device samples mosi, edge on which it changes miso), from the standard description of SPI modes 0 to 3:
#   mode 0 (cpol 0, cpha 0): sample on rising, change on falling       mode 1 (cpol 0, cpha 1): sample on falling, change on rising
#   mode 2 (cpol 1, cpha 0): sample on falling, change on rising       mode 3 (cpol 1, cpha 1): sample on rising, change on falling
STANDARD = {(0, 0): ("rising", "falling"), (0, 1): ("falling", "rising"), (1, 0): ("falling", "rising"), (1, 1): ("rising", "falling")}
MODES = sorted(STANDARD)


async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())


async def cycles(dut, n):
    for _ in range(n):
        await RisingEdge(dut.clk)


async def reset(dut, cycles_=3):
    dut.rst.value = 1
    await cycles(dut, cycles_)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def setup(dut, cpol=0, cpha=0):
    """Clock, inputs at rest, reset; the mode is applied before the reset so that sclk idles at the right level."""
    dut.start.value = 0
    dut.tx_data.value = 0
    dut.miso.value = 0
    dut.cpol.value = cpol
    dut.cpha.value = cpha
    dut.rst.value = 0
    await start_clock(dut)
    await reset(dut)


async def set_mode(dut, cpol, cpha):
    """Apply a mode while the master is idle and give sclk time to settle at the idle level."""
    dut.cpol.value = cpol
    dut.cpha.value = cpha
    await cycles(dut, 3)


async def begin(dut, data, cpol=None, cpha=None):
    """Offer a transfer for exactly one clock edge (the master takes it there if it is idle). Ends just after that edge."""
    dut.tx_data.value = data
    if cpol is not None:
        dut.cpol.value = cpol
    if cpha is not None:
        dut.cpha.value = cpha
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0


class Recorder:
    """Records cs_n, sclk, mosi, busy and done on every falling clock edge (index = number of falling edges so far)."""

    def __init__(self, dut):
        self.dut = dut
        self.cs, self.sclk, self.mosi, self.busy, self.done = [], [], [], [], []
        self._task = cocotb.start_soon(self._run())

    async def _run(self):
        d = self.dut
        while True:
            await FallingEdge(d.clk)
            self.cs.append(int(d.cs_n.value))
            self.sclk.append(int(d.sclk.value))
            self.mosi.append(int(d.mosi.value))
            self.busy.append(int(d.busy.value))
            self.done.append(int(d.done.value))

    def frames(self):
        """[(first sample with cs_n low, first sample with cs_n high again)] for every chip-select window recorded so far."""
        out, i, n = [], 0, len(self.cs)
        while i < n:
            if self.cs[i] == 0:
                j = i
                while j < n and self.cs[j] == 0:
                    j += 1
                out.append((i, j))
                i = j
            else:
                i += 1
        return out

    def edges(self, a, b):
        """[(sample index, 'rising' or 'falling')] for every sclk change in samples a to b (an edge is reported at the first sample showing the new level)."""
        return [(i, "rising" if self.sclk[i] == 1 else "falling") for i in range(max(a, 1), b) if self.sclk[i] != self.sclk[i - 1]]

    async def wait_for_done(self, limit):
        """Wait (in falling edges) until a done pulse has been recorded after now; returns its sample index. Fails if it takes longer than limit cycles."""
        start = len(self.done)
        for _ in range(limit):
            await FallingEdge(self.dut.clk)
            if 1 in self.done[start:]:
                return start + self.done[start:].index(1)
        raise AssertionError(f"no done pulse within {limit} clock cycles")


class SpiSlave:
    """A reference SPI slave for one mode, written from the standard table. It samples mosi on the sampling edge (the value just before the
    edge) and changes miso on the shifting edge; in the modes where the first bit must be ready before the first edge (cpha = 0) it puts it
    on miso as soon as cs_n goes low. `word` is what it sends; `sampled` is the list of mosi bits it saw in the current frame."""

    def __init__(self, dut, cpol, cpha, width=None):
        self.dut = dut
        self.cpol, self.cpha = cpol, cpha
        self.width = W if width is None else width
        self.sample_edge, self.shift_edge = STANDARD[(cpol, cpha)]
        self.word = 0
        self.sampled = []
        self._task = cocotb.start_soon(self._run())

    def _bit(self, i):
        return (self.word >> (self.width - 1 - i)) & 1

    def word_seen(self):
        """The word the slave sampled from mosi (most-significant bit first), or None if it did not sample exactly `width` bits."""
        if len(self.sampled) != self.width:
            return None
        return sum(b << (self.width - 1 - i) for i, b in enumerate(self.sampled))

    def stop(self):
        self._task.cancel()

    async def _run(self):
        d = self.dut
        prev_cs, prev_sclk, prev_mosi = 1, int(d.sclk.value), 0
        driven = 0
        while True:
            await FallingEdge(d.clk)
            cs, sclk, mosi = int(d.cs_n.value), int(d.sclk.value), int(d.mosi.value)
            if cs == 0 and prev_cs == 1:                       # selected
                self.sampled, driven = [], 0
                if self.cpha == 0:
                    d.miso.value = self._bit(0)
                    driven = 1
            if cs == 0 and sclk != prev_sclk:
                edge = "rising" if sclk == 1 else "falling"
                if edge == self.sample_edge:
                    self.sampled.append(prev_mosi)
                if edge == self.shift_edge and driven < self.width:
                    d.miso.value = self._bit(driven)
                    driven += 1
            prev_cs, prev_sclk, prev_mosi = cs, sclk, mosi
