# rtl-verification-lab
[![CI](https://github.com/baliyu/rtl-verification-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/baliyu/rtl-verification-lab/actions/workflows/ci.yml)

Small digital circuits, each written **twice, in Verilog and in VHDL**, and checked by **one set of Python tests** ([cocotb](https://www.cocotb.org/)) that run unchanged on both. Everything is simulated on a PC: no FPGA board is used or needed.

The point is verification, not just design: the tests check behaviour to the clock cycle, and a second tool breaks the circuits on purpose to prove that the tests notice.

## Status
- [x] **UART**: transmitter, receiver and a loopback top level (8N1)
- [x] **SPI master**: all four modes, any word length from 2 to 64 bits, one chip select
- [ ] Asynchronous FIFO that crosses between two clocks (planned)

## Why one testbench for two languages
A test written in Python looks at a circuit only through its ports, so it does not care whether the circuit is Verilog or VHDL. Running the same tests on both gives a direct check that the two implementations behave identically, and any difference shows up as a failing test in one language only. Verilog runs on Icarus Verilog, VHDL on GHDL.

## The UART
| | |
|---|---|
| Frame | start bit (0), 8 data bits least-significant first, one stop bit (1); no parity, no flow control |
| Speed | set by the parameter / generic `CLKS_PER_BIT` (clock cycles per bit, at least 4) |
| Reset | synchronous, active high |
| Transmitter `uart_tx` | `tx_data`, `tx_valid`, `tx_ready` handshake: a byte is taken on the clock edge where `tx_valid` and `tx_ready` are both 1; `tx_ready` is 1 only when idle; a `tx_valid` pulse while busy is ignored; every bit lasts exactly `CLKS_PER_BIT` cycles |
| Receiver `uart_rx` | two-flop input synchroniser; start bit confirmed half a bit later (a shorter glitch is ignored); each bit sampled near its middle; a good frame gives a one-cycle `rx_valid` pulse with the byte on `rx_data`; a bad stop bit gives a one-cycle `rx_error` pulse and the receiver waits for the line to go high (so a long break gives one error, not many) |
| `uart_loop` | a transmitter wired to a receiver, for end-to-end tests |

## The SPI master
| | |
|---|---|
| Modes | all four: `cpol` is the level `sclk` idles at, `cpha` chooses whether data is sampled on the first or the second edge of each bit; both are copied when the transfer starts |
| Word | `WIDTH` bits (generic / parameter, 2 to 64), most-significant bit first, in both directions at once |
| Speed | `CLKS_PER_HALF` system clocks per half period of `sclk` (1 or more) |
| Handshake | a transfer starts on the clock edge where `start` is 1 and `busy` is 0; a `start` pulse while busy is ignored; `done` is 1 for one clock at the end and `rx_data` then holds the received word |
| Timing | `cs_n` falls, the first `sclk` edge comes one half period later, then `2 x WIDTH` evenly spaced edges, and `cs_n` rises one half period after the last edge: low for exactly `(2 x WIDTH + 1) x CLKS_PER_HALF` clocks |
| Reset | synchronous, active high; abandons a transfer at once |

The device on the other end of the wires in the tests is a small SPI slave written from the **published table of the four modes** (which edge a device samples on, which edge it changes its output on) and not from the circuit's own logic, so a misreading of the standard cannot hide in both.

Circuits: `rtl/verilog/` (Verilog-2001) and `rtl/vhdl/` (VHDL-93). Tests: `tests/uart/` and `tests/spi/`.

<!-- results:start -->

### Results

Every block is built and run in both languages at each of its settings: **18 simulator runs** per push. The tests are the same Python for Verilog and VHDL.

**`uart_tx`**: 5 tests, run at `CLKS_PER_BIT=8`; `CLKS_PER_BIT=32`

- `line_idles_high_and_ready_after_reset`: After reset the line is high and the transmitter is ready, and stays that way.
- `every_byte_value_is_framed_exactly`: For all 256 byte values the frame is start, 8 data bits LSB first, stop, each exactly CLKS_PER_BIT cycles; tx_ready is low throughout and high right after.
- `back_to_back_frames_are_all_correct_and_close_together`: Sending 12 random bytes as fast as tx_ready allows gives 12 correct frames, each start bit 10 to 11 bit-times after the last.
- `a_valid_pulse_while_busy_is_ignored`: A tx_valid pulse in the middle of a frame (with different data) neither corrupts that frame nor starts another.
- `reset_in_the_middle_of_a_frame_returns_to_idle`: Reset during a frame puts the line back high and ready at once, and the next frame is still exact.

**`uart_rx`**: 9 tests, run at `CLKS_PER_BIT=8`; `CLKS_PER_BIT=32`

- `quiet_after_reset`: With the line idle, rx_valid and rx_error stay low.
- `every_byte_value_is_received_inside_its_stop_bit`: All 256 byte values arrive intact as a single one-cycle rx_valid pulse that falls inside the frame's stop bit, with no error.
- `random_bytes_back_to_back_with_random_gaps`: 200 random bytes, with gaps from none at all (the next start bit right after the stop bit) up to three bit-times, all arrive in order.
- `a_bad_stop_bit_is_an_error_and_the_receiver_recovers`: A frame whose stop bit is 0 gives exactly one rx_error pulse and no byte; the next good frame is received normally.
- `a_long_break_is_one_error_not_a_stream_of_them`: The line held low for 30 bit-times (a break) gives exactly one rx_error and no data; afterwards a good frame is received.
- `a_short_glitch_is_not_a_start_bit`: A low pulse of a quarter of a bit-time is ignored: no byte and no error; a good frame afterwards is still received.
- `reset_in_the_middle_of_a_frame_abandons_it`: Reset during a frame discards it (no byte, no error) and the receiver works normally afterwards.
- `tolerates_a_bit_time_error_of_one_clock`: With 32 or more clocks per bit, a sender that is one clock per bit fast or slow (about 3 %) is still received correctly.
- `a_badly_wrong_bit_time_is_not_received_correctly`: The test above has teeth: a sender 30 % slow is NOT received correctly (wrong data or errors), so the tolerance check can fail.

**`uart_loop`**: 1 test, run at `CLKS_PER_BIT=8`; `CLKS_PER_BIT=32`

- `random_bytes_go_through_in_order`: 150 random bytes sent through the transmitter come out of the receiver in the same order, with no error and one pulse each.

**`spi_master`**: 9 tests, run at `CLKS_PER_HALF=1 WIDTH=8`; `CLKS_PER_HALF=4 WIDTH=16`; `CLKS_PER_HALF=3 WIDTH=5`

- `idle_state_after_reset_for_both_idle_levels`: After reset, with the line idle: cs_n high, mosi low, busy and done low, and sclk sitting at the level cpol asks for, in either level.
- `every_mode_sends_and_receives_words_correctly`: In all four modes, 16 random words each way: the standard-table slave sees exactly the word sent on mosi, the master's rx_data is exactly the word the slave sent, done is one clock, busy was high throughout.
- `frame_timing_is_exact_in_every_mode`: cs_n is low for exactly (2*WIDTH+1)*H clocks, the first sclk edge is H clocks after cs_n falls, there are exactly 2*WIDTH edges H clocks apart, the last is H clocks before cs_n rises, done comes with cs_n rising, and afterwards sclk is back at the idle level and mosi low.
- `mosi_is_stable_when_sampled_and_changes_only_when_the_standard_says`: Against the standard table: mosi never changes at the edge where a device samples it, and changes only on the edge where devices shift (apart from being set when cs_n falls and cleared when it rises).
- `back_to_back_transfers_all_correct_with_one_clock_between`: Twelve transfers started as soon as the master is free are all correct, and cs_n is high for just one or two clocks between them.
- `a_start_pulse_while_busy_is_ignored`: A start pulse in the middle of a transfer, with different data, neither changes that transfer nor starts another.
- `mode_and_data_are_copied_when_the_transfer_starts`: Changing cpol, cpha and tx_data right after the start has no effect on the transfer in progress.
- `rx_data_holds_its_value_after_the_transfer`: rx_data keeps the received word, unchanged, for as long as the master stays idle.
- `reset_in_the_middle_of_a_transfer_returns_to_idle`: Reset during a transfer puts cs_n high, mosi low, busy low and sclk at the idle level at once, gives no done pulse, and the next transfer is correct.

### Breaking the circuits on purpose

`tools/mutate.py` makes 33 realistic bugs, one at a time, in each language, and runs the block's tests against each broken circuit. Of 66 broken circuits, **64 were caught** by at least one failing test and **2 survived**.

| Block | Bug | Verilog | VHDL |
|---|---|---|---|
| `uart_tx` | the start bit is sent as 1 instead of 0 | caught | caught |
| `uart_tx` | the first data bit is bit 7 instead of bit 0 | caught | caught |
| `uart_tx` | the transmitter skips the stop bit state | caught | caught |
| `uart_tx` | the start bit lasts one clock too few | caught | caught |
| `uart_tx` | each data bit lasts one clock too few | caught | caught |
| `uart_tx` | the stop bit lasts one clock too few | caught | caught |
| `uart_tx` | tx_ready goes high during the stop bit | caught | caught |
| `uart_tx` | reset does not put the line back to high | caught | caught |
| `uart_rx` | the receiver samples at the start of the bit, not the middle | caught | caught |
| `uart_rx` | a bad stop bit is never reported | caught | caught |
| `uart_rx` | bits are assembled most-significant first | caught | caught |
| `uart_rx` | a short glitch is accepted as a start bit | caught | caught |
| `uart_rx` | rx_valid is never cleared, so the pulse does not end | caught | caught |
| `uart_rx` | after a framing error the receiver does not wait for the line to go high | caught | caught |
| `uart_rx` | only seven data bits are collected | caught | caught |
| `uart_rx` | each data bit is sampled one clock earlier than the one before (a creeping bit time) | caught | caught |
| `uart_rx` | reset does nothing in the receiver | caught | caught |
| `spi_master` | the first bit sent in modes 0 and 2 is bit 0 instead of the top bit | caught | caught |
| `spi_master` | cpha is ignored: every transfer uses mode 0 or 2 timing | caught | caught |
| `spi_master` | cpol is ignored: sclk always idles low | caught | caught |
| `spi_master` | chip select is released one clock early | caught | caught |
| `spi_master` | every half period of sclk lasts one clock too few | caught | caught |
| `spi_master` | miso is sampled on the wrong edge of the bit | caught | caught |
| `spi_master` | rx_data never receives the word | caught | caught |
| `spi_master` | the done pulse never ends | caught | caught |
| `spi_master` | tx_data is read live, not copied at the start, on the first edges (modes 1 and 3) | caught | caught |
| `spi_master` | tx_data is read live, not copied at the start, on the second edges (modes 0 and 2) | caught | caught |
| `spi_master` | cpha is read live, not copied at the start, when deciding where to sample | caught | caught |
| `spi_master` | reset does nothing in the SPI master | caught | caught |
| `spi_master` | mosi stays at the last bit after the transfer instead of returning to low | caught | caught |
| `spi_master` | the transfer stops one bit early | caught | caught |
| `spi_master` | busy goes low at the last sclk edge, before the transfer is over | caught | caught |
| `uart_rx` | the two-flop input synchroniser is cut to one flop | **survived** | **survived** |

The surviving bug ("the two-flop input synchroniser is cut to one flop") is **expected** to survive, because it cannot be detected in RTL simulation: a simulator has no metastability, so a missing synchroniser only shows up in clock-domain-crossing analysis or on hardware.

<!-- results:end -->

## Run it yourself
On Ubuntu 24.04 or WSL2 (the setup script uses `sudo`, so it asks for your password):
```bash
git clone https://github.com/baliyu/rtl-verification-lab.git && cd rtl-verification-lab
bash tools/setup_ubuntu.sh                    # once: Icarus Verilog, GHDL, and a Python environment with cocotb and pytest
source ~/.venvs/rtl-verification-lab/bin/activate
python -m pytest -q                           # all simulator runs and the report check (about 30 seconds)
python tools/mutate.py                        # break the circuits on purpose (a few minutes); rewrites results/mutation.json
python tools/make_report.py                   # rewrite the results block above from the tests and results/mutation.json
```

## Limits (what this does not show)
- **Simulation of the RTL only.** The circuits were not synthesised, placed or timed, and never ran on an FPGA. A circuit that passes simulation can still fail on hardware, for example because of timing or a metastable input; simulators do not model that.
- **My reading of the UART.** One stop bit, no parity, no 9-bit mode, one sample per bit. The receiver was measured to cope with a sender one clock per bit fast or slow at 32 clocks per bit (about 3 %); that is a measurement of this design, not a general claim.
- **My reading of SPI.** A master only: one chip select, most-significant bit first, no clock stretching, no multi-master. `mosi` and `sclk` change on the same clock edge in the RTL, so on real hardware the output timing and the slave's setup and hold times would need separate attention.
- **The mutation list is hand-picked.** It is a set of plausible bugs, not a proof that the tests catch every bug.
- **Tested versions:** Icarus Verilog 12.0 and GHDL 4.1.0 (LLVM backend) on Ubuntu 24.04, with cocotb 2.1.0. Other versions were not tried.

## Licence
MIT (see `LICENSE`).
