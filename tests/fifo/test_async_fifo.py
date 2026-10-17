"""Tests of async_fifo, written once and run against both the Verilog and the VHDL circuit, with the real synchroniser and with a nasty one.

The two clocks are unrelated in speed and phase (see the settings the runner uses). A scoreboard in the testbench tracks every word in flight,
so a lost, repeated, reordered or invented word fails the test at once. A second variant of every run replaces the two-flop synchroniser by a
model that catches changing bits as either old or new at random, which is what exposes pointers that cross the clock boundary the wrong way.
Every test has a limit of 400 microseconds of simulated time (several times what the slowest legitimate run needs): a circuit that makes a test wait forever fails it.
"""
import cocotb
from cocotb.triggers import FallingEdge, RisingEdge, Timer

from fifo_bfm import ADDR_WIDTH, DATA_WIDTH, DEPTH, MASK, RPERIOD, SLOW, WPERIOD, Bench, reset_both, settle_and_check_flags, start_clocks, wait_cycles, word_number


async def setup(dut):
    await start_clocks(dut)
    await reset_both(dut)


@cocotb.test(timeout_time=400, timeout_unit="us")
async def flags_after_reset(dut):
    """After reset the FIFO reports empty and not full, and keeps doing so while nothing happens."""
    await setup(dut)
    for _ in range(10):
        assert (int(dut.r_empty.value), int(dut.w_full.value)) == (1, 0)
        await wait_cycles(1)


@cocotb.test(timeout_time=400, timeout_unit="us")
async def fill_to_full_then_drain_in_order(dut):
    """Writing with nothing reading fills the FIFO to exactly DEPTH words and then w_full holds it there however many more writes are attempted; draining gives back the first DEPTH words in order, and the flags end exact."""
    await setup(dut)
    bench = Bench(dut, seed=2, p_write=1.0, p_read=1.0)
    bench.read_on = False
    await wait_cycles(4 * DEPTH + 20)
    assert len(bench.expected) == DEPTH and bench.saw_write_while_full, "the FIFO did not fill to exactly DEPTH words"
    assert (int(dut.w_full.value), int(dut.r_empty.value)) == (1, 0)
    bench.write_on = False
    bench.read_on = True
    await wait_cycles(4 * DEPTH + 20)
    assert not bench.expected and bench.read == DEPTH
    await settle_and_check_flags(dut, bench)
    bench.stop()


@cocotb.test(timeout_time=400, timeout_unit="us")
async def reads_while_empty_and_writes_while_full_do_nothing(dut):
    """Read attempts on an empty FIFO change nothing (the words written afterwards come out in order), and a write attempted while full does not overwrite anything."""
    await setup(dut)
    bench = Bench(dut, seed=3, p_write=0.0, p_read=1.0)
    await wait_cycles(10)
    assert bench.saw_read_while_empty and bench.read == 0
    bench.p_write, bench.p_read = 0.5, 0.0
    await wait_cycles(4 * DEPTH + 20)                     # fills up and keeps trying to write
    assert len(bench.expected) == DEPTH and bench.saw_write_while_full
    bench.p_write, bench.p_read = 0.0, 1.0
    await wait_cycles(4 * DEPTH + 20)
    assert not bench.expected
    await settle_and_check_flags(dut, bench)
    bench.stop()


@cocotb.test(timeout_time=400, timeout_unit="us")
async def random_traffic_in_four_patterns_keeps_every_word_in_order(dut):
    """Four traffic patterns in a row (writer faster, reader faster, balanced, and alternating bursts), at least 30 times the FIFO depth in words: nothing is lost, repeated or reordered, and the traffic really did fill the FIFO and empty it."""
    await setup(dut)
    bench = Bench(dut, seed=4)
    for p_write, p_read in ((0.9, 0.2), (0.2, 0.9), (0.5, 0.5)):
        bench.p_write, bench.p_read = p_write, p_read
        await Timer(700 * WPERIOD, unit="ns")
    for _ in range(6):                                    # bursts: all writing, then all reading
        bench.p_write, bench.p_read = 1.0, 0.0
        await Timer(3 * DEPTH * WPERIOD, unit="ns")
        bench.p_write, bench.p_read = 0.0, 1.0
        await Timer(3 * DEPTH * RPERIOD, unit="ns")
    bench.p_write, bench.p_read = 0.0, 1.0
    await wait_cycles(4 * DEPTH + 20)
    assert not bench.expected, "words were left over after draining"
    assert bench.written == bench.read and bench.written > 30 * DEPTH, f"only {bench.written} words went through"
    assert bench.saw_full and bench.saw_empty_with_data and bench.saw_write_while_full and bench.saw_read_while_empty, "the traffic never reached full / empty"
    await settle_and_check_flags(dut, bench)
    bench.stop()


@cocotb.test(timeout_time=400, timeout_unit="us")
async def a_reader_asking_every_clock_never_gets_a_word_that_is_not_there(dut):
    """A reader that asks on every read clock while a writer adds a word only now and then (so the FIFO is nearly always empty, and every write is a pointer change the reader must judge correctly) never gets a word that is not there."""
    await setup(dut)
    bench = Bench(dut, seed=7, p_write=0.15, p_read=1.0)
    await Timer(3000 * WPERIOD, unit="ns")
    bench.p_write = 0.0
    await wait_cycles(4 * DEPTH + 20)
    assert bench.written > 100 and not bench.expected and bench.read == bench.written
    await settle_and_check_flags(dut, bench)
    bench.stop()


@cocotb.test(timeout_time=400, timeout_unit="us")
async def a_writer_asking_every_clock_never_overruns_a_slow_reader(dut):
    """A writer that asks on every write clock while a reader takes a word only now and then (so the FIFO is nearly always full, and every read is a pointer change the writer must judge correctly) never overflows it."""
    await setup(dut)
    bench = Bench(dut, seed=8, p_write=1.0, p_read=0.15)
    await Timer(3000 * RPERIOD, unit="ns")
    bench.p_read = 1.0
    bench.p_write = 0.0
    await wait_cycles(4 * DEPTH + 20)
    assert bench.read > 100 and not bench.expected and bench.read == bench.written
    await settle_and_check_flags(dut, bench)
    bench.stop()


@cocotb.test(timeout_time=400, timeout_unit="us")
async def every_data_bit_carries_a_one_and_a_zero(dut):
    """Words with a single bit set, a single bit clear, all zeros, all ones and alternating bits all come back unchanged, so every bit of the data path is used both ways."""
    await setup(dut)
    words = [1 << k for k in range(DATA_WIDTH)] + [MASK ^ (1 << k) for k in range(DATA_WIDTH)] + [0, MASK, 0x55555555 & MASK, 0xAAAAAAAA & MASK]
    got = []

    async def reader():
        while len(got) < len(words):
            await FallingEdge(dut.rclk)
            if int(dut.r_empty.value) == 0:
                got.append(int(dut.r_data.value))
                dut.r_en.value = 1
                await FallingEdge(dut.rclk)
                dut.r_en.value = 0
    cocotb.start_soon(reader())
    for w in words:
        while True:
            await FallingEdge(dut.wclk)
            if int(dut.w_full.value) == 0:
                break
        dut.w_data.value = w
        dut.w_en.value = 1
        await FallingEdge(dut.wclk)
        dut.w_en.value = 0
    for _ in range(100):                                  # the reader needs two read clocks per word: wait until every word has arrived
        if len(got) == len(words):
            break
        await wait_cycles(1)
    assert got == words


@cocotb.test(timeout_time=400, timeout_unit="us")
async def flags_follow_within_a_few_clocks(dut):
    """One word written into an empty FIFO makes r_empty go low within 5 read clocks, and one word read from a full FIFO makes w_full go low within 5 write clocks."""
    await setup(dut)
    await FallingEdge(dut.wclk)
    dut.w_data.value = word_number(0)
    dut.w_en.value = 1
    await FallingEdge(dut.wclk)
    dut.w_en.value = 0
    t0 = cocotb.utils.get_sim_time("ns")
    waited = 0
    while int(dut.r_empty.value) == 1:
        await FallingEdge(dut.rclk)
        waited += 1
        assert waited <= 6, "r_empty stayed high for more than 5 read clocks after a write"
    assert cocotb.utils.get_sim_time("ns") - t0 <= 5 * RPERIOD + WPERIOD, "r_empty took too long to fall"
    dut.r_en.value = 1
    await FallingEdge(dut.rclk)
    dut.r_en.value = 0
    await wait_cycles(8)
    assert (int(dut.r_empty.value), int(dut.w_full.value)) == (1, 0)
    for n in range(DEPTH):                                # fill it
        while int(dut.w_full.value) == 1:
            await FallingEdge(dut.wclk)
        await FallingEdge(dut.wclk)
        dut.w_data.value = word_number(n)
        dut.w_en.value = 1
        await FallingEdge(dut.wclk)
        dut.w_en.value = 0
    await wait_cycles(8)
    assert int(dut.w_full.value) == 1
    await FallingEdge(dut.rclk)
    dut.r_en.value = 1
    await FallingEdge(dut.rclk)
    dut.r_en.value = 0
    waited = 0
    while int(dut.w_full.value) == 1:
        await FallingEdge(dut.wclk)
        waited += 1
        assert waited <= 6 + 2 * (RPERIOD // WPERIOD + 1), "w_full stayed high for too long after a read"


@cocotb.test(timeout_time=400, timeout_unit="us")
async def reset_in_the_middle_discards_the_contents(dut):
    """Resetting both domains while words are stored (and traffic is running) leaves the FIFO empty, not full, and with no stale word: only words written afterwards come out."""
    await setup(dut)
    bench = Bench(dut, seed=5, p_write=0.8, p_read=0.1)
    await wait_cycles(20)
    assert bench.expected, "nothing was stored before the reset"
    bench.stop()
    await reset_both(dut)
    assert (int(dut.r_empty.value), int(dut.w_full.value)) == (1, 0), "flags are wrong after the reset"
    bench2 = Bench(dut, seed=6, p_write=0.5, p_read=0.5)
    await wait_cycles(40)
    bench2.p_write, bench2.p_read = 0.0, 1.0
    await wait_cycles(4 * DEPTH + 20)
    assert not bench2.expected and bench2.read == bench2.written > 8
    await settle_and_check_flags(dut, bench2)
    bench2.stop()
