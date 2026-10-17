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

# id, what is broken, block whose tests are run, the change for Verilog and for VHDL, expectation (None, or why it cannot be detected), and optionally settings that
# replace the block's mutation setting. A change is (file, old text, new text, which occurrence), or a list of such changes when one bug needs several edits.
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
    ("rx-synchroniser-removed", "the two-flop input synchroniser is cut to one flop", "uart_rx",
     ("uart_rx.v", "rxd_s <= rxd_m;", "rxd_s <= rxd;", 1), ("uart_rx.vhd", "rxd_s <= rxd_m;", "rxd_s <= rxd;", 1),
     "a simulator has no metastability, so a missing synchroniser only shows up in clock-domain-crossing analysis or on hardware"),
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
    ("fifo-full-never-raised", "w_full never goes high, so the FIFO overflows", "async_fifo",
     ("async_fifo.v", "w_full <= full_next;", "w_full <= 1'b0;", 1), ("async_fifo.vhd", "wfull_r  <= full_next;", "wfull_r  <= '0';", 1), None),
    ("fifo-empty-never-raised", "r_empty never goes high, so the FIFO underflows", "async_fifo",
     ("async_fifo.v", "r_empty <= empty_next;", "r_empty <= 1'b0;", 1), ("async_fifo.vhd", "rempty_r <= empty_next;", "rempty_r <= '0';", 1), None),
    ("fifo-full-compare-not-inverted", "the full test does not invert the top two bits of the synchronised read pointer", "async_fifo",
     ("async_fifo.v", "{~wq_rptr[ADDR_WIDTH:ADDR_WIDTH-1], wq_rptr[ADDR_WIDTH-2:0]}", "wq_rptr", 1),
     ("async_fifo.vhd", "((not wq_rptr(ADDR_WIDTH downto ADDR_WIDTH - 1)) & wq_rptr(ADDR_WIDTH - 2 downto 0))", "wq_rptr", 1), None),
    ("fifo-empty-uses-current-pointer", "the empty test uses the read pointer as it is now, not as it will be after this clock", "async_fifo",
     ("async_fifo.v", "(rgray_next == rq_wptr)", "(rptr == rq_wptr)", 1), ("async_fifo.vhd", "std_logic_vector(rgray_next) = rq_wptr", "std_logic_vector(rptr) = rq_wptr", 1), None),
    ("fifo-full-uses-current-pointer", "the full test uses the write pointer as it is now, not as it will be after this clock", "async_fifo",
     ("async_fifo.v", "(wgray_next == {", "(wptr == {", 1), ("async_fifo.vhd", "std_logic_vector(wgray_next) = ((not", "std_logic_vector(wptr) = ((not", 1), None),
    ("fifo-binary-pointers-cross", "plain binary pointers cross between the clocks instead of Gray-coded ones (several bits change at once)", "async_fifo",
     [("async_fifo.v", "(wbin_next >> 1) ^ wbin_next", "wbin_next", 1), ("async_fifo.v", "(rbin_next >> 1) ^ rbin_next", "rbin_next", 1),
      ("async_fifo.v", "{~wq_rptr[ADDR_WIDTH:ADDR_WIDTH-1], wq_rptr[ADDR_WIDTH-2:0]}", "{~wq_rptr[ADDR_WIDTH], wq_rptr[ADDR_WIDTH-1:0]}", 1)],
     [("async_fifo.vhd", "(wbin_next srl 1) xor wbin_next", "wbin_next", 1), ("async_fifo.vhd", "(rbin_next srl 1) xor rbin_next", "rbin_next", 1),
      ("async_fifo.vhd", "((not wq_rptr(ADDR_WIDTH downto ADDR_WIDTH - 1)) & wq_rptr(ADDR_WIDTH - 2 downto 0))", "((not wq_rptr(ADDR_WIDTH downto ADDR_WIDTH)) & wq_rptr(ADDR_WIDTH - 1 downto 0))", 1)],
     None),
    ("fifo-binary-pointers-cross-plain-sim", "the same binary-pointer bug, simulated with an ordinary two-flop synchroniser", "async_fifo",
     [("async_fifo.v", "(wbin_next >> 1) ^ wbin_next", "wbin_next", 1), ("async_fifo.v", "(rbin_next >> 1) ^ rbin_next", "rbin_next", 1),
      ("async_fifo.v", "{~wq_rptr[ADDR_WIDTH:ADDR_WIDTH-1], wq_rptr[ADDR_WIDTH-2:0]}", "{~wq_rptr[ADDR_WIDTH], wq_rptr[ADDR_WIDTH-1:0]}", 1)],
     [("async_fifo.vhd", "(wbin_next srl 1) xor wbin_next", "wbin_next", 1), ("async_fifo.vhd", "(rbin_next srl 1) xor rbin_next", "rbin_next", 1),
      ("async_fifo.vhd", "((not wq_rptr(ADDR_WIDTH downto ADDR_WIDTH - 1)) & wq_rptr(ADDR_WIDTH - 2 downto 0))", "((not wq_rptr(ADDR_WIDTH downto ADDR_WIDTH)) & wq_rptr(ADDR_WIDTH - 1 downto 0))", 1)],
     "in a zero-delay simulation every bit of a pointer reaches the other clock at the same moment, so a binary pointer works; the bug only appears when the wires are skewed (the nasty synchroniser above) or on real hardware",
     {"SYNC": "rtl"}),
    ("fifo-writes-when-full", "a word is stored even when the FIFO is full, overwriting unread data", "async_fifo",
     ("async_fifo.v", "if (w_push) mem[", "if (w_en) mem[", 1), ("async_fifo.vhd", "if w_push = '1' then", "if w_en = '1' then", 1), None),
    ("fifo-read-pointer-moves-when-empty", "the read pointer advances on a read of an empty FIFO", "async_fifo",
     ("async_fifo.v", "r_en && !r_empty;", "r_en;", 1), ("async_fifo.vhd", "r_pop      <= r_en and not rempty_r;", "r_pop      <= r_en;", 1), None),
    ("fifo-write-pointer-moves-when-full", "the write pointer advances on a write to a full FIFO", "async_fifo",
     ("async_fifo.v", "wbin + (w_push ? 1 : 0)", "wbin + (w_en ? 1 : 0)", 1), ("async_fifo.vhd", "wbin + 1 when w_push = '1' else wbin", "wbin + 1 when w_en = '1' else wbin", 1), None),
    ("fifo-reads-one-word-ahead", "r_data shows the word after the oldest one", "async_fifo",
     ("async_fifo.v", "assign r_data = mem[rbin[ADDR_WIDTH-1:0]];", "assign r_data = mem[rbin[ADDR_WIDTH-1:0] + 1'b1];", 1),
     ("async_fifo.vhd", "r_data <= mem(to_integer(rbin(ADDR_WIDTH - 1 downto 0)));", "r_data <= mem((to_integer(rbin(ADDR_WIDTH - 1 downto 0)) + 1) mod DEPTH);", 1), None),
    ("fifo-write-reset-ignored", "reset does nothing in the write clock domain", "async_fifo",
     ("async_fifo.v", "if (wrst) begin", "if (1'b0) begin", 1), ("async_fifo.vhd", "if wrst = '1' then", "if false then", 1), None),
    ("fifo-read-reset-ignored", "reset does nothing in the read clock domain", "async_fifo",
     ("async_fifo.v", "if (rrst) begin", "if (1'b0) begin", 1), ("async_fifo.vhd", "if rrst = '1' then", "if false then", 1), None),
    ("fifo-ram-written-at-the-gray-address", "the RAM is written at the Gray-coded address but read at the binary one", "async_fifo",
     ("async_fifo.v", "mem[wbin[ADDR_WIDTH-1:0]] <= w_data;", "mem[wptr[ADDR_WIDTH-1:0]] <= w_data;", 1),
     ("async_fifo.vhd", "mem(to_integer(wbin(ADDR_WIDTH - 1 downto 0))) <= w_data;", "mem(to_integer(wptr(ADDR_WIDTH - 1 downto 0))) <= w_data;", 1), None),
    ("fifo-one-flop-synchroniser", "the two-flop synchroniser is cut to one flop", "async_fifo",
     ("sync_2ff.v", "s2 <= s1;", "s2 <= d;", 1), ("sync_2ff.vhd", "s2 <= s1;", "s2 <= d;", 1),
     "a simulator has no metastability, so it cannot tell one flop from two; this needs a clock-domain-crossing checker or an analysis of how long the first flop takes to settle",
     {"SYNC": "rtl"}),
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
    mid, lang, block, edits, undetectable, override = task
    with tempfile.TemporaryDirectory() as tmp:
        rtl = Path(tmp) / "rtl"
        shutil.copytree(ROOT / "rtl" / lang, rtl)
        for fname, old, new, nth in edits:
            mutated = apply((rtl / fname).read_text(encoding="utf-8"), old, new, nth)
            if mutated is None:
                return mid, lang, "ERROR: the text to change was not found"
            (rtl / fname).write_text(mutated, encoding="utf-8")
        config = {**BLOCKS[block]["mutation_config"], **override}
        try:
            ran, failed = run(lang, block, config, Path(tmp) / "work", rtl_dir=rtl)
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
        for mid, what, block, _, _, expect, *_ in MUTATIONS:
            print(f"{mid:38} {block:10} {what}" + ("   [expected to survive]" if expect else ""))
        return 0
    chosen = [m for m in MUTATIONS if not a.blocks or m[2] in a.blocks]
    tasks = [(m[0], lang, m[2], spec if isinstance(spec, list) else [spec], m[5], m[6] if len(m) > 6 else {})
             for m in chosen for lang, spec in (("verilog", m[3]), ("vhdl", m[4]))]
    expected_survivors = {m[0] for m in MUTATIONS if m[5]}
    results = {}
    with ProcessPoolExecutor(max_workers=max(1, a.jobs)) as pool:
        for mid, lang, status in pool.map(run_one, tasks):
            results[(mid, lang)] = status
            ok = (status.startswith("killed") and "expected to survive" not in status) or (mid in expected_survivors and status == "SURVIVED")
            print(f"{'ok     ' if ok else 'PROBLEM'} {mid:38} {lang:8} {status}", flush=True)
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
