# rtl-verification-lab
[![CI](https://github.com/baliyu/rtl-verification-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/baliyu/rtl-verification-lab/actions/workflows/ci.yml)

Small digital circuits, each written **twice, in Verilog and in VHDL**, and checked by **one set of Python tests** ([cocotb](https://www.cocotb.org/)) that run unchanged on both. Everything is simulated on a PC: no FPGA board is used or needed.

The point is verification, not just design: the tests check behaviour to the clock cycle, and a second tool breaks the circuits on purpose to prove that the tests notice.

## Status
- [x] **UART**: transmitter, receiver and a loopback top level (8N1)
- [ ] SPI master (planned)
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

Circuits: `rtl/verilog/` (Verilog-2001) and `rtl/vhdl/` (VHDL-93). Tests: `tests/uart/`.

<!-- results:start -->

### Results

Every block is built and run in both languages at 8 and 32 clock cycles per bit: **12 simulator runs** per push (2 languages x 3 blocks x 2 bit rates). The tests, which are the same Python for Verilog and VHDL:

**`uart_tx`**: 5 tests

- `line_idles_high_and_ready_after_reset`: After reset the line is high and the transmitter is ready, and stays that way.
- `every_byte_value_is_framed_exactly`: For all 256 byte values the frame is start, 8 data bits LSB first, stop, each exactly CLKS_PER_BIT cycles; tx_ready is low throughout and high right after.
- `back_to_back_frames_are_all_correct_and_close_together`: Sending 12 random bytes as fast as tx_ready allows gives 12 correct frames, each start bit 10 to 11 bit-times after the last.
- `a_valid_pulse_while_busy_is_ignored`: A tx_valid pulse in the middle of a frame (with different data) neither corrupts that frame nor starts another.
- `reset_in_the_middle_of_a_frame_returns_to_idle`: Reset during a frame puts the line back high and ready at once, and the next frame is still exact.

**`uart_rx`**: 9 tests

- `quiet_after_reset`: With the line idle, rx_valid and rx_error stay low.
- `every_byte_value_is_received_inside_its_stop_bit`: All 256 byte values arrive intact as a single one-cycle rx_valid pulse that falls inside the frame's stop bit, with no error.
- `random_bytes_back_to_back_with_random_gaps`: 200 random bytes, with gaps from none at all (the next start bit right after the stop bit) up to three bit-times, all arrive in order.
- `a_bad_stop_bit_is_an_error_and_the_receiver_recovers`: A frame whose stop bit is 0 gives exactly one rx_error pulse and no byte; the next good frame is received normally.
- `a_long_break_is_one_error_not_a_stream_of_them`: The line held low for 30 bit-times (a break) gives exactly one rx_error and no data; afterwards a good frame is received.
- `a_short_glitch_is_not_a_start_bit`: A low pulse of a quarter of a bit-time is ignored: no byte and no error; a good frame afterwards is still received.
- `reset_in_the_middle_of_a_frame_abandons_it`: Reset during a frame discards it (no byte, no error) and the receiver works normally afterwards.
- `tolerates_a_bit_time_error_of_one_clock`: With 32 or more clocks per bit, a sender that is one clock per bit fast or slow (about 3 %) is still received correctly.
- `a_badly_wrong_bit_time_is_not_received_correctly`: The test above has teeth: a sender 30 % slow is NOT received correctly (wrong data or errors), so the tolerance check can fail.

**`uart_loop`**: 1 test

- `random_bytes_go_through_in_order`: 150 random bytes sent through the transmitter come out of the receiver in the same order, with no error and one pulse each.

### Breaking the circuits on purpose

`tools/mutate.py` makes 18 realistic bugs, one at a time, in each language, and runs the block's tests against each broken circuit. Of 36 broken circuits, **34 were caught** by at least one failing test and **2 survived**.

| Bug | Verilog | VHDL |
|---|---|---|
| the start bit is sent as 1 instead of 0 | caught | caught |
| the first data bit is bit 7 instead of bit 0 | caught | caught |
| the transmitter skips the stop bit state | caught | caught |
| the start bit lasts one clock too few | caught | caught |
| each data bit lasts one clock too few | caught | caught |
| the stop bit lasts one clock too few | caught | caught |
| tx_ready goes high during the stop bit | caught | caught |
| reset does not put the line back to high | caught | caught |
| the receiver samples at the start of the bit, not the middle | caught | caught |
| a bad stop bit is never reported | caught | caught |
| bits are assembled most-significant first | caught | caught |
| a short glitch is accepted as a start bit | caught | caught |
| rx_valid is never cleared, so the pulse does not end | caught | caught |
| after a framing error the receiver does not wait for the line to go high | caught | caught |
| only seven data bits are collected | caught | caught |
| each data bit is sampled one clock earlier than the one before (a creeping bit time) | caught | caught |
| reset does nothing in the receiver | caught | caught |
| the two-flop input synchroniser is cut to one flop | **survived** | **survived** |

The surviving bug ("the two-flop input synchroniser is cut to one flop") is **expected** to survive, because it cannot be detected in RTL simulation: a simulator has no metastability, so a missing synchroniser only shows up in clock-domain-crossing analysis or on hardware.

<!-- results:end -->

## Run it yourself
On Ubuntu 24.04 or WSL2 (the setup script uses `sudo`, so it asks for your password):
```bash
git clone https://github.com/baliyu/rtl-verification-lab.git && cd rtl-verification-lab
bash tools/setup_ubuntu.sh                    # once: Icarus Verilog, GHDL, and a Python environment with cocotb and pytest
source ~/.venvs/rtl-verification-lab/bin/activate
python -m pytest -q                           # all simulator runs and the report check (about 30 seconds)
python tools/mutate.py                        # break the circuits on purpose (about two minutes); rewrites results/mutation.json
python tools/make_report.py                   # rewrite the results block above from the tests and results/mutation.json
```

## Limits (what this does not show)
- **Simulation of the RTL only.** The circuits were not synthesised, placed or timed, and never ran on an FPGA. A circuit that passes simulation can still fail on hardware, for example because of timing or a metastable input; simulators do not model that.
- **My reading of the UART.** One stop bit, no parity, no 9-bit mode, one sample per bit. The receiver was measured to cope with a sender one clock per bit fast or slow at 32 clocks per bit (about 3 %); that is a measurement of this design, not a general claim.
- **The mutation list is hand-picked.** It is a set of plausible bugs, not a proof that the tests catch every bug.
- **Tested versions:** Icarus Verilog 12.0 and GHDL 4.1.0 (LLVM backend) on Ubuntu 24.04, with cocotb 2.1.0. Other versions were not tried.

## Licence
MIT (see `LICENSE`).
