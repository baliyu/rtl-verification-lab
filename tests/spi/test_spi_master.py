"""Tests of spi_master, written once and run against both the Verilog and the VHDL circuit.

The device on the other end of the wires is SpiSlave (tests/spi/spi_bfm.py), built from the published table of the four SPI modes and not from
the circuit's own logic, so a misreading of the standard cannot hide in both. Timing is checked to the clock cycle on a recording of the wires.
"""
import random

import cocotb

from spi_bfm import H, MODES, STANDARD, W, Recorder, SpiSlave, begin, cycles, reset, set_mode, setup

TIMEOUT = (2 * W + 6) * H + 20            # clock cycles within which a transfer must finish


def word(rng):
    return rng.randrange(1 << W)


async def transfer(dut, slave, rec, mosi_word, miso_word):
    """Run one transfer against the slave; returns the sample index of the done pulse."""
    slave.word = miso_word
    await begin(dut, mosi_word)
    return await rec.wait_for_done(TIMEOUT)


@cocotb.test()
async def idle_state_after_reset_for_both_idle_levels(dut):
    """After reset, with the line idle: cs_n high, mosi low, busy and done low, and sclk sitting at the level cpol asks for, in either level."""
    for cpol in (0, 1):
        await setup(dut, cpol=cpol)
        await cycles(dut, 4)
        for sig, want in ((dut.cs_n, 1), (dut.mosi, 0), (dut.busy, 0), (dut.done, 0), (dut.sclk, cpol)):
            assert int(sig.value) == want, f"cpol={cpol}: {sig._name} = {int(sig.value)}, expected {want}"
        await set_mode(dut, 1 - cpol, 0)
        assert int(dut.sclk.value) == 1 - cpol, "sclk does not follow cpol while idle"


@cocotb.test()
async def every_mode_sends_and_receives_words_correctly(dut):
    """In all four modes, 16 random words each way: the standard-table slave sees exactly the word sent on mosi, the master's rx_data is exactly the word the slave sent, done is one clock, busy was high throughout."""
    rng = random.Random(4)
    for cpol, cpha in MODES:
        await setup(dut, cpol, cpha)
        rec, slave = Recorder(dut), SpiSlave(dut, cpol, cpha)
        for n in range(16):
            mosi_word = (0, (1 << W) - 1, 1 << (W - 1), 1)[n] if n < 4 else word(rng)     # all zeros, all ones, only the top bit, only the bottom bit, then random
            miso_word = word(rng)
            done_at = await transfer(dut, slave, rec, mosi_word, miso_word)
            await cycles(dut, 2)                                                           # let the recorder take the samples after the pulse
            assert slave.word_seen() == mosi_word, f"mode {(cpol, cpha)}: slave saw {slave.word_seen()} instead of {mosi_word:#x}"
            assert int(dut.rx_data.value) == miso_word, f"mode {(cpol, cpha)}: rx_data {int(dut.rx_data.value):#x} instead of {miso_word:#x}"
            assert rec.done[done_at] == 1 and rec.done[done_at + 1] == 0, "done lasted more than one clock"
            a, b = rec.frames()[-1]
            assert all(rec.busy[a:b]), "busy dropped during the transfer"
            assert rec.busy[done_at] == 0
        slave.stop()


@cocotb.test()
async def frame_timing_is_exact_in_every_mode(dut):
    """cs_n is low for exactly (2*WIDTH+1)*H clocks, the first sclk edge is H clocks after cs_n falls, there are exactly 2*WIDTH edges H clocks apart, the last is H clocks before cs_n rises, done comes with cs_n rising, and afterwards sclk is back at the idle level and mosi low."""
    for cpol, cpha in MODES:
        await setup(dut, cpol, cpha)
        rec, slave = Recorder(dut), SpiSlave(dut, cpol, cpha)
        for n in range(3):
            await transfer(dut, slave, rec, 0xA5A5A5A5 & ((1 << W) - 1), n)
        await cycles(dut, 5)
        frames = rec.frames()
        assert len(frames) == 3
        for a, b in frames:
            assert b - a == (2 * W + 1) * H, f"mode {(cpol, cpha)}: cs_n low for {b - a} clocks, expected {(2 * W + 1) * H}"
            edges = rec.edges(a, b)
            assert len(edges) == 2 * W
            assert edges[0][0] - a == H and b - edges[-1][0] == H
            assert all(y[0] - x[0] == H for x, y in zip(edges, edges[1:])), "sclk edges are not evenly spaced"
            assert edges[0][1] == ("rising" if cpol == 0 else "falling"), "the first edge leaves the idle level"
            assert rec.done[b] == 1, "done does not come when cs_n rises"
        assert all(s == cpol for s in rec.sclk[frames[-1][1]:]) and all(m == 0 for m in rec.mosi[frames[-1][1]:]), "the wires are not back at idle"
        slave.stop()


@cocotb.test()
async def mosi_is_stable_when_sampled_and_changes_only_when_the_standard_says(dut):
    """Against the standard table: mosi never changes at the edge where a device samples it, and changes only on the edge where devices shift (apart from being set when cs_n falls and cleared when it rises)."""
    rng = random.Random(5)
    for cpol, cpha in MODES:
        sample_edge, shift_edge = STANDARD[(cpol, cpha)]
        await setup(dut, cpol, cpha)
        rec, slave = Recorder(dut), SpiSlave(dut, cpol, cpha)
        for _ in range(6):
            await transfer(dut, slave, rec, word(rng), word(rng))
        await cycles(dut, 3)
        for a, b in rec.frames():
            edges = rec.edges(a, b)
            for i, direction in edges:
                if direction == sample_edge:
                    assert rec.mosi[i] == rec.mosi[i - 1], f"mode {(cpol, cpha)}: mosi changed on the {sample_edge} edge, where it is sampled"
            allowed = {i for i, d in edges if d == shift_edge} | {a, b}
            changes = {i for i in range(a, b + 1) if rec.mosi[i] != rec.mosi[i - 1]}
            assert changes <= allowed, f"mode {(cpol, cpha)}: mosi changed at an unexpected time"
        slave.stop()


@cocotb.test()
async def back_to_back_transfers_all_correct_with_one_clock_between(dut):
    """Twelve transfers started as soon as the master is free are all correct, and cs_n is high for just one or two clocks between them."""
    rng = random.Random(6)
    await setup(dut, 1, 1)
    rec, slave = Recorder(dut), SpiSlave(dut, 1, 1)
    sent, got = [], []
    for _ in range(12):
        mosi_word, miso_word = word(rng), word(rng)
        sent.append((mosi_word, miso_word))
        slave.word = miso_word
        while int(dut.busy.value) == 1:
            await cycles(dut, 1)
        await begin(dut, mosi_word)
        await rec.wait_for_done(TIMEOUT)
        got.append((slave.word_seen(), int(dut.rx_data.value)))
    assert got == sent
    frames = rec.frames()
    assert all(1 <= b[0] - a[1] <= 2 for a, b in zip(frames, frames[1:])), [b[0] - a[1] for a, b in zip(frames, frames[1:])]
    slave.stop()


@cocotb.test()
async def a_start_pulse_while_busy_is_ignored(dut):
    """A start pulse in the middle of a transfer, with different data, neither changes that transfer nor starts another."""
    await setup(dut, 0, 0)
    rec, slave = Recorder(dut), SpiSlave(dut, 0, 0)
    slave.word = 0x5A5A5A5A & ((1 << W) - 1)
    await begin(dut, 0xC3C3C3C3 & ((1 << W) - 1))
    await cycles(dut, (W * H) + 1)
    await begin(dut, 0x3C3C3C3C & ((1 << W) - 1))
    await rec.wait_for_done(TIMEOUT)
    await cycles(dut, (2 * W + 6) * H)
    assert len(rec.frames()) == 1
    assert slave.word_seen() == 0xC3C3C3C3 & ((1 << W) - 1)


@cocotb.test()
async def mode_and_data_are_copied_when_the_transfer_starts(dut):
    """Changing cpol, cpha and tx_data right after the start has no effect on the transfer in progress."""
    rng = random.Random(8)
    for cpol, cpha in MODES:
        await setup(dut, cpol, cpha)
        rec, slave = Recorder(dut), SpiSlave(dut, cpol, cpha)
        mosi_word, miso_word = word(rng), word(rng)
        slave.word = miso_word
        await begin(dut, mosi_word)
        dut.cpol.value, dut.cpha.value, dut.tx_data.value = 1 - cpol, 1 - cpha, mosi_word ^ ((1 << W) - 1)
        await rec.wait_for_done(TIMEOUT)
        assert slave.word_seen() == mosi_word and int(dut.rx_data.value) == miso_word, f"mode {(cpol, cpha)}"
        slave.stop()


@cocotb.test()
async def rx_data_holds_its_value_after_the_transfer(dut):
    """rx_data keeps the received word, unchanged, for as long as the master stays idle."""
    await setup(dut, 0, 1)
    rec, slave = Recorder(dut), SpiSlave(dut, 0, 1)
    miso_word = 0x2D2D2D2D & ((1 << W) - 1) or 1
    await transfer(dut, slave, rec, 0, miso_word)
    for _ in range(30):
        await cycles(dut, 1)
        assert int(dut.rx_data.value) == miso_word


@cocotb.test()
async def reset_in_the_middle_of_a_transfer_returns_to_idle(dut):
    """Reset during a transfer puts cs_n high, mosi low, busy low and sclk at the idle level at once, gives no done pulse, and the next transfer is correct."""
    for cpol, cpha in ((0, 0), (1, 1)):
        await setup(dut, cpol, cpha)
        rec, slave = Recorder(dut), SpiSlave(dut, cpol, cpha)
        slave.word = (1 << W) - 1
        await begin(dut, 0)
        await cycles(dut, W * H)
        dut.rst.value = 1
        await cycles(dut, 2)
        dut.rst.value = 0
        await cycles(dut, 2)
        assert (int(dut.cs_n.value), int(dut.mosi.value), int(dut.busy.value), int(dut.sclk.value)) == (1, 0, 0, cpol)
        assert not any(rec.done), "a done pulse appeared although the transfer was abandoned"
        rng = random.Random(9)
        mosi_word, miso_word = word(rng), word(rng)
        await transfer(dut, slave, rec, mosi_word, miso_word)
        assert slave.word_seen() == mosi_word and int(dut.rx_data.value) == miso_word
        slave.stop()
