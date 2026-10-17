"""End-to-end test of uart_loop (a transmitter wired to a receiver), the same for Verilog and VHDL."""
import random

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge

from uart_bfm import CLKS, RxMonitor, cycles, reset, start_clock


@cocotb.test()
async def random_bytes_go_through_in_order(dut):
    """150 random bytes sent through the transmitter come out of the receiver in the same order, with no error and one pulse each."""
    dut.tx_data.value = 0
    dut.tx_valid.value = 0
    await start_clock(dut)
    await reset(dut)
    mon = RxMonitor(dut)
    rng = random.Random(99)
    data = [rng.randrange(256) for _ in range(150)]
    for byte in data:
        while True:                                   # wait until the transmitter is ready
            await FallingEdge(dut.clk)
            if int(dut.tx_ready.value) == 1:
                break
        dut.tx_data.value = byte
        dut.tx_valid.value = 1
        await RisingEdge(dut.clk)
        dut.tx_valid.value = 0
        if rng.random() < 0.3:
            await cycles(dut, rng.randrange(1, 3 * CLKS))
    await cycles(dut, 12 * CLKS)
    assert mon.bytes() == data
    assert not mon.errors
