#!/usr/bin/env python3
"""tools/mutate.py - break the circuits on purpose, one realistic bug at a time, and check that the tests notice.

    python3 tools/mutate.py                       run every mutation in both languages (about two minutes with four jobs)
    python3 tools/mutate.py --blocks spi_master   run only the mutations of the named blocks and update just those entries of results/mutation.json
    python3 tools/mutate.py --jobs 1              run them one at a time (slower, same results)
    python3 tools/mutate.py --list                show the mutations without running them

For each mutation a copy of the circuit with ONE change is built and the tests of the affected block are run at the mutation setting of that block.
A mutation is "killed" when at least one test fails, which is what we want. A mutation that survives is a hole in the tests, unless it is
listed as undetectable in RTL simulation (with the reason). A mutation whose text cannot be found, or which stops the circuit from
building, is reported as an error (the table below is out of date with the circuits). Exit status 0 only if everything is as expected.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "uart"))
from runner import BLOCKS, describe, run  # noqa: E402

# id, what is broken, block whose tests are run, (file, old text, new text, which occurrence) for Verilog and for VHDL, expectation
MUTATIONS = [
    ("tx-start-bit-high", "the start bit is sent as 1 instead of 0", "uart_tx",
     ("uart_tx.v", "txd     <= 1'b0;", "txd     <= 1'b1;", 1), ("uart_tx.vhd", "txd_r   <= '0';", "txd_r   <= '1';", 1), None),
    ("tx-msb-first", "the first data bit is bit 7 instead of bit 0", "uart_tx",
     ("uart_tx.v", "txd     <= shreg[0];", "txd     <= shreg[7];", 1), ("uart_tx.vhd", "txd_r   <= shreg(0);", "txd_r   <= shreg(7);", 1), None),
    ("tx-no-stop-bit", "the transmitter skips the stop bit state", "uart_tx",
     ("uart_tx.v", "state <= S_STOP;", "state <= S_IDLE;", 1), ("uart_tx.vhd", "state <= S_STOP;", "state <= S_IDLE;", 1), None),
    ("tx-short-start-bit", "the start bit lasts one clock too few", "uart_tx",
     ("uart_tx.v", "if (clk_cnt == CLKS_PER_BIT - 1) begin", "if (clk_cnt == CLKS_PER_BIT - 2) begin", 1),
     ("uart_tx.vhd", "if clk_cnt = CLKS_PER_BIT - 1 then", "if clk_cnt = CLKS_PER_BIT - 2 then", 1), None),
    ("tx-short-data-bits", "each data bit lasts one clock too few", "uart_tx",
     ("uart_tx.v", "if (clk_cnt == CLKS_PER_BIT - 1) begin", "if (clk_cnt == CLKS_PER_BIT - 2) begin", 2),
     ("uart_tx.vhd", "if clk_cnt = CLKS_PER_BIT - 1 then", "if clk_cnt = CLKS_PER_BIT - 2 then", 2), None),
    ("tx-short-stop-bit", "the stop bit lasts one clock too few", "uart_tx",
     ("uart_tx.v", "if (clk_cnt == CLKS_PER_BIT - 1) begin", "if (clk_cnt == CLKS_PER_BIT - 2) begin", 3),
     ("uart_tx.vhd", "if clk_cnt = CLKS_PER_BIT - 1 then", "if clk_cnt = CLKS_PER_BIT - 2 then", 3), None),
    ("tx-ready-too-early", "tx_ready goes high during the stop bit", "uart_tx",
     ("uart_tx.v", "assign tx_ready = (state == S_IDLE);", "assign tx_ready = (state == S_IDLE) || (state == S_STOP);", 1),
     ("uart_tx.vhd", "tx_ready <= '1' when state = S_IDLE else '0';", "tx_ready <= '1' when state = S_IDLE or state = S_STOP else '0';", 1), None),
    ("tx-reset-leaves-line-low", "reset does not put the line back to high", "uart_tx",
     ("uart_tx.v", "txd     <= 1'b1;", "txd     <= txd;", 1), ("uart_tx.vhd", "txd_r   <= '1';", "txd_r   <= txd_r;", 1), None),
    ("rx-samples-at-bit-edge", "the receiver samples at the start of the bit, not the middle", "uart_rx",
     ("uart_rx.v", "if (clk_cnt == (CLKS_PER_BIT / 2) - 1) begin", "if (clk_cnt == 0) begin", 1),
     ("uart_rx.vhd", "if clk_cnt = (CLKS_PER_BIT / 2) - 1 then", "if clk_cnt = 0 then", 1), None),
    ("rx-error-never-reported", "a bad stop bit is never reported", "uart_rx",
     ("uart_rx.v", "rx_error <= 1'b1;", "rx_error <= 1'b0;", 1), ("uart_rx.vhd", "error_r <= '1';", "error_r <= '0';", 1), None),
    ("rx-msb-first", "bits are assembled most-significant first", "uart_rx",
     ("uart_rx.v", "{rxd_s, shreg[7:1]}", "{shreg[6:0], rxd_s}", 1), ("uart_rx.vhd", "rxd_s & shreg(7 downto 1)", "shreg(6 downto 0) & rxd_s", 1), None),
    ("rx-glitch-accepted", "a short glitch is accepted as a start bit", "uart_rx",
     ("uart_rx.v", "if (rxd_s == 1'b0) begin         // still low", "if (1'b1) begin         // still low", 1),
     ("uart_rx.vhd", "if rxd_s = '0' then                   -- still low", "if true then                   -- still low", 1), None),
    ("rx-valid-stays-high", "rx_valid is never cleared, so the pulse does not end", "uart_rx",
     ("uart_rx.v", "rx_valid <= 1'b0;", "rx_valid <= rx_valid;", 2), ("uart_rx.vhd", "valid_r <= '0';", "valid_r <= valid_r;", 2), None),
    ("rx-no-wait-after-error", "after a framing error the receiver does not wait for the line to go high", "uart_rx",
     ("uart_rx.v", "state    <= S_WAIT;", "state    <= S_IDLE;", 1), ("uart_rx.vhd", "state   <= S_WAIT;", "state   <= S_IDLE;", 1), None),
    ("rx-seven-data-bits", "only seven data bits are collected", "uart_rx",
     ("uart_rx.v", "if (bit_idx == 3'd7) state <= S_STOP;", "if (bit_idx == 3'd6) state <= S_STOP;", 1),
     ("uart_rx.vhd", "if bit_idx = 7 then", "if bit_idx = 6 then", 1), None),
    ("rx-data-bits-sampled-early", "each data bit is sampled one clock earlier than the one before (a creeping bit time)", "uart_rx",
     ("uart_rx.v", "if (clk_cnt == CLKS_PER_BIT - 1) begin", "if (clk_cnt == CLKS_PER_BIT - 2) begin", 1),
     ("uart_rx.vhd", "if clk_cnt = CLKS_PER_BIT - 1 then", "if clk_cnt = CLKS_PER_BIT - 2 then", 1), None),
    ("rx-reset-ignored", "reset does nothing in the receiver", "uart_rx",
     ("uart_rx.v", "if (rst) begin", "if (1'b0) begin", 1), ("uart_rx.vhd", "if rst = '1' then", "if false then", 1), None),
    ("spi-first-bit-wrong", "the first bit sent in modes 0 and 2 is bit 0 instead of the top bit", "spi_master",
     ("spi_master.v", "mosi     <= cpha ? 1'b0 : tx_data[WIDTH-1];", "mosi     <= cpha ? 1'b0 : tx_data[0];", 1),
     ("spi_master.vhd", "mosi_r <= tx_data(WIDTH - 1);", "mosi_r <= tx_data(0);", 1), None),
    ("spi-cpha-ignored", "cpha is ignored: every transfer uses mode 0 or 2 timing", "spi_master",
     ("spi_master.v", "cpha_r   <= cpha;", "cpha_r   <= 1'b0;", 1), ("spi_master.vhd", "cpha_r   <= cpha;", "cpha_r   <= '0';", 1), None),
    ("spi-cpol-ignored", "cpol is ignored: sclk always idles low", "spi_master",
     ("spi_master.v", "sclk <= cpol;", "sclk <= 1'b0;", 1), ("spi_master.vhd", "sclk_r <= cpol;", "sclk_r <= '0';", 1), None),
    ("spi-cs-released-early", "chip select is released one clock early", "spi_master",
     ("spi_master.v", "if (cnt == CLKS_PER_HALF - 1) begin", "if (cnt == CLKS_PER_HALF - 2) begin", 2),
     ("spi_master.vhd", "if cnt = CLKS_PER_HALF - 1 then", "if cnt = CLKS_PER_HALF - 2 then", 2), None),
    ("spi-half-period-short", "every half period of sclk lasts one clock too few", "spi_master",
     ("spi_master.v", "if (cnt == CLKS_PER_HALF - 1) begin", "if (cnt == CLKS_PER_HALF - 2) begin", 1),
     ("spi_master.vhd", "if cnt = CLKS_PER_HALF - 1 then", "if cnt = CLKS_PER_HALF - 2 then", 1), None),
    ("spi-sampling-edge-swapped", "miso is sampled on the wrong edge of the bit", "spi_master",
     ("spi_master.v", "if (cpha_r == 1'b0) rx_r <= {rx_r[WIDTH-2:0], miso};", "if (cpha_r == 1'b1) rx_r <= {rx_r[WIDTH-2:0], miso};", 1),
     ("spi_master.vhd", "if cpha_r = '0' then", "if cpha_r = '1' then", 1), None),
    ("spi-rx-data-never-updated", "rx_data never receives the word", "spi_master",
     ("spi_master.v", "rx_data <= rx_r;", "rx_data <= rx_data;", 1), ("spi_master.vhd", "rx_data_r <= rx_r;", "rx_data_r <= rx_data_r;", 1), None),
    ("spi-done-never-ends", "the done pulse never ends", "spi_master",
     ("spi_master.v", "done <= 1'b0;", "done <= done;", 1), ("spi_master.vhd", "done_r <= '0';", "done_r <= done_r;", 1), None),
    ("spi-live-data-on-first-edges", "tx_data is read live, not copied at the start, on the first edges (modes 1 and 3)", "spi_master",
     ("spi_master.v", "mosi <= tx_r[WIDTH-1 - (edge_cnt >> 1)];", "mosi <= tx_data[WIDTH-1 - (edge_cnt >> 1)];", 1),
     ("spi_master.vhd", "mosi_r <= tx_r(WIDTH - 1 - edge_cnt / 2);", "mosi_r <= tx_data(WIDTH - 1 - edge_cnt / 2);", 1), None),
    ("spi-live-data-on-second-edges", "tx_data is read live, not copied at the start, on the second edges (modes 0 and 2)", "spi_master",
     ("spi_master.v", "mosi <= tx_r[WIDTH-2 - (edge_cnt >> 1)];", "mosi <= tx_data[WIDTH-2 - (edge_cnt >> 1)];", 1),
     ("spi_master.vhd", "mosi_r <= tx_r(WIDTH - 2 - edge_cnt / 2);", "mosi_r <= tx_data(WIDTH - 2 - edge_cnt / 2);", 1), None),
    ("spi-live-cpha-for-sampling", "cpha is read live, not copied at the start, when deciding where to sample", "spi_master",
     ("spi_master.v", "if (cpha_r == 1'b1) rx_r <=", "if (cpha == 1'b1) rx_r <=", 1), ("spi_master.vhd", "if cpha_r = '1' then", "if cpha = '1' then", 1), None),
    ("spi-reset-ignored", "reset does nothing in the SPI master", "spi_master",
     ("spi_master.v", "if (rst) begin", "if (1'b0) begin", 1), ("spi_master.vhd", "if rst = '1' then", "if false then", 1), None),
    ("spi-mosi-left-high", "mosi stays at the last bit after the transfer instead of returning to low", "spi_master",
     ("spi_master.v", "mosi    <= 1'b0;", "mosi    <= mosi;", 1), ("spi_master.vhd", "mosi_r    <= '0';", "mosi_r    <= mosi_r;", 2), None),
    ("spi-one-bit-short", "the transfer stops one bit early", "spi_master",
     ("spi_master.v", "if (edge_cnt == 2 * WIDTH - 1) begin", "if (edge_cnt == 2 * WIDTH - 3) begin", 1),
     ("spi_master.vhd", "if edge_cnt = 2 * WIDTH - 1 then", "if edge_cnt = 2 * WIDTH - 3 then", 1), None),
    ("spi-busy-drops-early", "busy goes low at the last sclk edge, before the transfer is over", "spi_master",
     ("spi_master.v", "state <= S_HOLD;", "state <= S_HOLD; busy <= 1'b0;", 1), ("spi_master.vhd", "state <= S_HOLD;", "state <= S_HOLD; busy_r <= '0';", 1), None),
    ("rx-synchroniser-removed", "the two-flop input synchroniser is cut to one flop", "uart_rx",
     ("uart_rx.v", "rxd_s <= rxd_m;", "rxd_s <= rxd;", 1), ("uart_rx.vhd", "rxd_s <= rxd_m;", "rxd_s <= rxd;", 1),
     "a simulator has no metastability, so a missing synchroniser only shows up in clock-domain-crossing analysis or on hardware"),
]


def apply(text, old, new, nth):
    """Replace the nth occurrence (1-based) of old by new; None if there are fewer than nth occurrences."""
    pos = -1
    for _ in range(nth):
        pos = text.find(old, pos + 1)
        if pos < 0:
            return None
    return text[:pos] + new + text[pos + len(old):]


def run_one(task):
    """Build one mutated circuit and run its block's tests. Returns (id, language, status text); a worker process runs this."""
    mid, lang, block, fname, old, new, nth, undetectable = task
    with tempfile.TemporaryDirectory() as tmp:
        rtl = Path(tmp) / "rtl"
        shutil.copytree(ROOT / "rtl" / lang, rtl)
        text = (rtl / fname).read_text(encoding="utf-8")
        mutated = apply(text, old, new, nth)
        if mutated is None:
            return mid, lang, "ERROR: the text to change was not found"
        (rtl / fname).write_text(mutated, encoding="utf-8")
        try:
            ran, failed = run(lang, block, BLOCKS[block]["mutation_config"], Path(tmp) / "work", rtl_dir=rtl)
        except Exception as e:                                   # noqa: BLE001
            return mid, lang, f"ERROR: the mutated circuit does not build or run ({type(e).__name__})"
        status = f"killed by {len(failed)} of {ran} tests" if failed else "SURVIVED"
        if failed and undetectable:
            status += " (expected to survive!)"
        return mid, lang, status


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true", help="show the mutations and exit")
    ap.add_argument("--no-write", action="store_true", help="do not write results/mutation.json")
    ap.add_argument("--blocks", nargs="+", choices=sorted(BLOCKS), help="run only the mutations of these blocks (the other entries of results/mutation.json are kept)")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1), help="how many broken circuits to simulate at the same time (default: up to 4)")
    a = ap.parse_args(argv)
    if a.list:
        for mid, what, block, _, _, expect in MUTATIONS:
            print(f"{mid:30} {block:10} {what}" + ("   [expected to survive]" if expect else ""))
        return 0
    chosen = [m for m in MUTATIONS if not a.blocks or m[2] in a.blocks]
    tasks = [(mid, lang, block, *spec, undetectable) for mid, what, block, verilog, vhdl, undetectable in chosen
             for lang, spec in (("verilog", verilog), ("vhdl", vhdl))]
    expected_survivors = {m[0] for m in MUTATIONS if m[5]}
    results = {}
    with ProcessPoolExecutor(max_workers=max(1, a.jobs)) as pool:
        for mid, lang, status in pool.map(run_one, tasks):
            results[(mid, lang)] = status
            ok = (status.startswith("killed") and "expected to survive" not in status) or (mid in expected_survivors and status == "SURVIVED")
            print(f"{'ok     ' if ok else 'PROBLEM'} {mid:30} {lang:8} {status}", flush=True)
    problems = [f"{mid} ({lang}): {status}" for (mid, lang), status in results.items()
                if not ((status.startswith("killed") and "expected to survive" not in status) or (mid in expected_survivors and status == "SURVIVED"))]
    if not a.no_write:
        out = ROOT / "results" / "mutation.json"
        out.parent.mkdir(exist_ok=True)
        verdict = lambda s: "killed" if s.startswith("killed") else ("survived" if s == "SURVIVED" else "error")   # noqa: E731
        new = {k: verdict(v) for k, v in results.items()}
        if a.blocks and out.exists():                            # keep the recorded results of the blocks that were not run
            old = {(m["id"], m["language"]): m["result"] for m in json.loads(out.read_text(encoding="utf-8"))["mutants"]}
            new = {**old, **new}
        order = [(m[0], lang) for m in MUTATIONS for lang in ("verilog", "vhdl")]
        data = {"expected_survivors": sorted(expected_survivors), "mutants": [{"id": i, "language": lang, "result": new[(i, lang)]} for i, lang in order if (i, lang) in new]}
        out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    killed = sum(1 for v in results.values() if v.startswith("killed"))
    print(f"\n{len(results)} mutants: {killed} killed, {sum(1 for v in results.values() if v == 'SURVIVED')} survived "
          f"({sum(1 for m in chosen if m[5]) * 2} of them expected), {len(problems)} problems")
    for p in problems:
        print("  PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
