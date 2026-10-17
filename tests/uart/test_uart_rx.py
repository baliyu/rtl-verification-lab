"""Tests of uart_rx, written once and run against both the Verilog and the VHDL circuit.

A bit-banging model drives the rxd line with exact bit times; a monitor records every cycle in which rx_valid or rx_error is high,
so a pulse that lasts two cycles, a missing pulse or a spurious one all show up.
"""
import random

import cocotb

from uart_bfm import CLKS, RxMonitor, cycles, drive_bits, frame_bits, reset, send_frame, start_clock


async def setup(dut):
    dut.rxd.value = 1
    await start_clock(dut)
    await reset(dut)
    return RxMonitor(dut)


async def idle(dut, n):
    dut.rxd.value = 1
    await cycles(dut, n)


@cocotb.test()
async def quiet_after_reset(dut):
    """With the line idle, rx_valid and rx_error stay low."""
    mon = await setup(dut)
    await idle(dut, 10 * CLKS)
    assert not mon.valid and not mon.errors


@cocotb.test()
async def every_byte_value_is_received_inside_its_stop_bit(dut):
    """All 256 byte values arrive intact as a single one-cycle rx_valid pulse that falls inside the frame's stop bit, with no error."""
    mon = await setup(dut)
    starts = []
    for byte in range(256):
        starts.append(mon.cycle)
        await send_frame(dut, byte)
        await idle(dut, CLKS)
    await idle(dut, 2 * CLKS)
    assert mon.bytes() == list(range(256)), "wrong, missing or repeated bytes (a pulse longer than one cycle shows up as a repeat)"
    assert not mon.errors
    for start, (when, _) in zip(starts, mon.valid):
        assert 9 * CLKS <= when - start <= 10 * CLKS + 1, f"rx_valid came {when - start} cycles after the start bit began"


@cocotb.test()
async def random_bytes_back_to_back_with_random_gaps(dut):
    """200 random bytes, with gaps from none at all (the next start bit right after the stop bit) up to three bit-times, all arrive in order."""
    mon = await setup(dut)
    rng = random.Random(2026)
    data = [rng.randrange(256) for _ in range(200)]
    for byte in data:
        await send_frame(dut, byte)
        await idle(dut, rng.choice([0, 0, 1, CLKS // 2, CLKS, 3 * CLKS]))
    await idle(dut, 2 * CLKS)
    assert mon.bytes() == data
    assert not mon.errors


@cocotb.test()
async def a_bad_stop_bit_is_an_error_and_the_receiver_recovers(dut):
    """A frame whose stop bit is 0 gives exactly one rx_error pulse and no byte; the next good frame is received normally."""
    mon = await setup(dut)
    await send_frame(dut, 0x3C, stop=0)
    await idle(dut, 3 * CLKS)
    assert len(mon.errors) == 1 and not mon.valid
    await send_frame(dut, 0xA5)
    await idle(dut, 2 * CLKS)
    assert mon.bytes() == [0xA5] and len(mon.errors) == 1


@cocotb.test()
async def a_long_break_is_one_error_not_a_stream_of_them(dut):
    """The line held low for 30 bit-times (a break) gives exactly one rx_error and no data; afterwards a good frame is received."""
    mon = await setup(dut)
    dut.rxd.value = 0
    await cycles(dut, 30 * CLKS)
    await idle(dut, 3 * CLKS)
    assert len(mon.errors) == 1 and not mon.valid
    await send_frame(dut, 0x5A)
    await idle(dut, 2 * CLKS)
    assert mon.bytes() == [0x5A]


@cocotb.test()
async def a_short_glitch_is_not_a_start_bit(dut):
    """A low pulse of a quarter of a bit-time is ignored: no byte and no error; a good frame afterwards is still received."""
    mon = await setup(dut)
    dut.rxd.value = 0
    await cycles(dut, CLKS // 4)
    await idle(dut, 4 * CLKS)
    assert not mon.valid and not mon.errors
    await send_frame(dut, 0xC3)
    await idle(dut, 2 * CLKS)
    assert mon.bytes() == [0xC3] and not mon.errors


@cocotb.test()
async def reset_in_the_middle_of_a_frame_abandons_it(dut):
    """Reset during a frame discards it (no byte, no error) and the receiver works normally afterwards."""
    mon = await setup(dut)
    await drive_bits(dut, frame_bits(0x5A)[:4], CLKS)      # the start bit and three data bits
    dut.rst.value = 1
    await cycles(dut, 2)
    dut.rst.value = 0
    await idle(dut, 3 * CLKS)                              # the rest of the line is held high
    assert not mon.valid and not mon.errors
    await send_frame(dut, 0x96)
    await idle(dut, 2 * CLKS)
    assert mon.bytes() == [0x96]


@cocotb.test(skip=CLKS < 32)
async def tolerates_a_bit_time_error_of_one_clock(dut):
    """With 32 or more clocks per bit, a sender that is one clock per bit fast or slow (about 3 %) is still received correctly."""
    mon = await setup(dut)
    rng = random.Random(11)
    sent = []
    for bit_clks in (CLKS - 1, CLKS + 1):
        for _ in range(40):
            byte = rng.randrange(256)
            sent.append(byte)
            await send_frame(dut, byte, bit_clks=bit_clks)
            await idle(dut, bit_clks)
    await idle(dut, 2 * CLKS)
    assert mon.bytes() == sent and not mon.errors


@cocotb.test(skip=CLKS < 32)
async def a_badly_wrong_bit_time_is_not_received_correctly(dut):
    """The test above has teeth: a sender 30 % slow is NOT received correctly (wrong data or errors), so the tolerance check can fail."""
    mon = await setup(dut)
    rng = random.Random(12)
    sent = []
    for _ in range(40):
        byte = rng.randrange(256)
        sent.append(byte)
        await send_frame(dut, byte, bit_clks=int(CLKS * 1.3))
        await idle(dut, CLKS)
    await idle(dut, 2 * CLKS)
    assert mon.bytes() != sent or mon.errors
