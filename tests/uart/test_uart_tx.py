"""Tests of uart_tx, written once and run against both the Verilog and the VHDL circuit.

The frame check is exact to the clock cycle: the start bit, every data bit and the stop bit last exactly CLKS_PER_BIT cycles.
"""
import random

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge

from uart_bfm import CLKS, cycles, frame_bits, reset, start_clock


async def present(dut, byte):
    """Offer one byte for exactly one clock edge (the circuit takes it there if it is ready). Ends just after that edge."""
    dut.tx_data.value = byte
    dut.tx_valid.value = 1
    await RisingEdge(dut.clk)
    dut.tx_valid.value = 0


async def sample_txd(dut, n):
    """(txd, tx_ready) on each of the next n falling edges."""
    out = []
    for _ in range(n):
        await FallingEdge(dut.clk)
        out.append((int(dut.txd.value), int(dut.tx_ready.value)))
    return out


async def setup(dut):
    dut.tx_data.value = 0
    dut.tx_valid.value = 0
    await start_clock(dut)
    await reset(dut)


def decode(levels):
    """Frames found in a list of line levels (one per clock): [(start index, byte, stop bit)]. Each bit is read at its middle."""
    frames, i = [], 1
    while i < len(levels):
        if levels[i - 1] == 1 and levels[i] == 0 and i + 10 * CLKS <= len(levels):
            mid = [levels[i + k * CLKS + CLKS // 2] for k in range(10)]
            frames.append((i, sum(b << k for k, b in enumerate(mid[1:9])), mid[9]))
            i += 10 * CLKS
        else:
            i += 1
    return frames


@cocotb.test()
async def line_idles_high_and_ready_after_reset(dut):
    """After reset the line is high and the transmitter is ready, and stays that way."""
    await setup(dut)
    for txd, ready in await sample_txd(dut, 5 * CLKS):
        assert (txd, ready) == (1, 1)


@cocotb.test()
async def every_byte_value_is_framed_exactly(dut):
    """For all 256 byte values the frame is start, 8 data bits LSB first, stop, each exactly CLKS_PER_BIT cycles; tx_ready is low throughout and high right after."""
    await setup(dut)
    for byte in range(256):
        await present(dut, byte)
        samples = await sample_txd(dut, 10 * CLKS + 2)
        expected = [bit for bit in frame_bits(byte) for _ in range(CLKS)]
        assert [s[0] for s in samples[:10 * CLKS]] == expected, f"byte {byte:#04x}: wrong waveform"
        assert all(s[1] == 0 for s in samples[:10 * CLKS]), f"byte {byte:#04x}: tx_ready was high during the frame"
        assert samples[10 * CLKS] == (1, 1), f"byte {byte:#04x}: not ready right after the stop bit"
        assert samples[10 * CLKS + 1] == (1, 1)


@cocotb.test()
async def back_to_back_frames_are_all_correct_and_close_together(dut):
    """Sending 12 random bytes as fast as tx_ready allows gives 12 correct frames, each start bit 10 to 11 bit-times after the last."""
    await setup(dut)
    rng = random.Random(7)
    data = [rng.randrange(256) for _ in range(12)]
    levels = []

    async def line_recorder():
        while True:
            await FallingEdge(dut.clk)
            levels.append(int(dut.txd.value))

    cocotb.start_soon(line_recorder())
    for byte in data:
        while True:
            await FallingEdge(dut.clk)
            if int(dut.tx_ready.value) == 1:
                break
        await present(dut, byte)
    await cycles(dut, 12 * CLKS)
    frames = decode(levels)
    assert [b for _, b, _ in frames] == data
    assert all(stop == 1 for _, _, stop in frames)
    gaps = [b[0] - a[0] for a, b in zip(frames, frames[1:])]
    assert all(10 * CLKS <= g <= 10 * CLKS + 2 for g in gaps), gaps


@cocotb.test()
async def a_valid_pulse_while_busy_is_ignored(dut):
    """A tx_valid pulse in the middle of a frame (with different data) neither corrupts that frame nor starts another."""
    await setup(dut)
    levels = []

    async def line_recorder():
        while True:
            await FallingEdge(dut.clk)
            levels.append(int(dut.txd.value))

    cocotb.start_soon(line_recorder())
    await present(dut, 0xA5)
    await cycles(dut, 3 * CLKS)
    await present(dut, 0x3C)                       # the transmitter is busy: this must be ignored
    await cycles(dut, 14 * CLKS)
    frames = decode(levels)
    assert [b for _, b, _ in frames] == [0xA5]


@cocotb.test()
async def reset_in_the_middle_of_a_frame_returns_to_idle(dut):
    """Reset during a frame puts the line back high and ready at once, and the next frame is still exact."""
    await setup(dut)
    await present(dut, 0x00)
    await cycles(dut, 3 * CLKS + 2)
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await FallingEdge(dut.clk)
    assert (int(dut.txd.value), int(dut.tx_ready.value)) == (1, 1)
    await RisingEdge(dut.clk)
    await present(dut, 0x96)
    samples = await sample_txd(dut, 10 * CLKS)
    assert [s[0] for s in samples] == [bit for bit in frame_bits(0x96) for _ in range(CLKS)]
