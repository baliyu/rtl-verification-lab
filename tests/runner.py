"""Build one circuit for one simulator and run its cocotb tests.

Used by the regression tests (tests/test_regression.py) and by the mutation checker (tools/mutate.py).
Verilog runs on Icarus Verilog, VHDL on GHDL; the Python tests for each block are the same for both.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parents[1]
SIMULATOR = {"verilog": "icarus", "vhdl": "ghdl"}
EXTENSION = {"verilog": ".v", "vhdl": ".vhd"}
def fifo_sources(lang, config, rtl_dir):
    """The files of the FIFO: the real two-flop synchroniser, or (SYNC = meta) the test model that catches changing bits as old or new at random."""
    ext = EXTENSION[lang]
    sync = rtl_dir / f"sync_2ff{ext}" if config["SYNC"] == "rtl" else ROOT / "tests" / "fifo" / "models" / f"sync_2ff_meta{ext}"
    return [sync, rtl_dir / f"async_fifo{ext}"]


FIFO = {"DATA_WIDTH", "ADDR_WIDTH"}                # of a FIFO's settings, only these go into the circuit; the rest (SYNC, clock periods) are for the testbench
BLOCKS = {                                   # toplevel -> files, cocotb test module, test folder, the settings it is run at, and the one used for mutation checks
    "uart_tx": {"files": ["uart_tx"], "module": "test_uart_tx", "dir": "uart",
                "configs": [{"CLKS_PER_BIT": 8}, {"CLKS_PER_BIT": 32}], "mutation_config": {"CLKS_PER_BIT": 32}},
    "uart_rx": {"files": ["uart_rx"], "module": "test_uart_rx", "dir": "uart",
                "configs": [{"CLKS_PER_BIT": 8}, {"CLKS_PER_BIT": 32}], "mutation_config": {"CLKS_PER_BIT": 32}},
    "uart_loop": {"files": ["uart_tx", "uart_rx", "uart_loop"], "module": "test_uart_loop", "dir": "uart",
                  "configs": [{"CLKS_PER_BIT": 8}, {"CLKS_PER_BIT": 32}], "mutation_config": {"CLKS_PER_BIT": 32}},
    "spi_master": {"files": ["spi_master"], "module": "test_spi_master", "dir": "spi",
                   "configs": [{"CLKS_PER_HALF": 1, "WIDTH": 8}, {"CLKS_PER_HALF": 4, "WIDTH": 16}, {"CLKS_PER_HALF": 3, "WIDTH": 5}],
                   "mutation_config": {"CLKS_PER_HALF": 3, "WIDTH": 8}},
    "async_fifo": {"files": fifo_sources, "hdl_params": ["DATA_WIDTH", "ADDR_WIDTH"], "module": "test_async_fifo", "dir": "fifo",
                   "configs": [{"SYNC": "rtl", "DATA_WIDTH": 8, "ADDR_WIDTH": 3, "WPERIOD": 10, "RPERIOD": 10, "RPHASE": 3},
                               {"SYNC": "rtl", "DATA_WIDTH": 5, "ADDR_WIDTH": 2, "WPERIOD": 7, "RPERIOD": 23, "RPHASE": 0},
                               {"SYNC": "rtl", "DATA_WIDTH": 16, "ADDR_WIDTH": 4, "WPERIOD": 23, "RPERIOD": 7, "RPHASE": 5},
                               {"SYNC": "meta", "DATA_WIDTH": 8, "ADDR_WIDTH": 3, "WPERIOD": 10, "RPERIOD": 3, "RPHASE": 1},
                               {"SYNC": "meta", "DATA_WIDTH": 8, "ADDR_WIDTH": 3, "WPERIOD": 3, "RPERIOD": 10, "RPHASE": 1},
                               {"SYNC": "meta", "DATA_WIDTH": 5, "ADDR_WIDTH": 2, "WPERIOD": 13, "RPERIOD": 17, "RPHASE": 2}],
                   "mutation_config": {"SYNC": "meta", "DATA_WIDTH": 8, "ADDR_WIDTH": 3, "WPERIOD": 10, "RPERIOD": 3, "RPHASE": 1}},
}


def describe(config):
    """A setting as text, for test names and the README: CLKS_PER_BIT=8, CLKS_PER_HALF=3 WIDTH=5, or for the FIFO a sentence."""
    if "SYNC" in config:
        return (f"{'plain' if config['SYNC'] == 'rtl' else 'nasty'} synchroniser, {config['DATA_WIDTH']} bits x {2 ** config['ADDR_WIDTH']} words, "
                f"write clock {config['WPERIOD']} ns, read clock {config['RPERIOD']} ns (offset {config['RPHASE']} ns)")
    return " ".join(f"{k}={v}" for k, v in config.items())


def run(lang, block, config, work_dir, rtl_dir=None):
    """Build `block` in `lang` with the given settings (a dict such as {"CLKS_PER_BIT": 8}) and run its tests.

    Returns (number of tests run, [names of the tests that failed]). A circuit that does not build raises an exception.
    """
    rtl_dir = Path(rtl_dir) if rtl_dir else ROOT / "rtl" / lang
    spec = BLOCKS[block]
    files = spec["files"]
    sources = files(lang, config, rtl_dir) if callable(files) else [rtl_dir / f"{f}{EXTENSION[lang]}" for f in files]
    hdl_params = {k: config[k] for k in spec["hdl_params"]} if "hdl_params" in spec else dict(config)
    work = Path(work_dir)
    runner = get_runner(SIMULATOR[lang])
    work.mkdir(parents=True, exist_ok=True)
    try:
        runner.build(sources=sources, hdl_toplevel=block, parameters=hdl_params, build_dir=work / "build", always=True,
                     timescale=("1ns", "1ps"),           # Icarus would otherwise simulate with a time precision of one second
                     log_file=work / "build.log")
    except Exception as e:                               # noqa: BLE001
        raise RuntimeError(f"{lang} {block} did not build:\n{tail(work / 'build.log')}") from e
    results = work / "results.xml"
    # GHDL's LLVM backend looks for the elaborated program in the folder it runs in, so VHDL runs in the build folder;
    # Icarus Verilog runs from the test folder.
    tests_dir = str(ROOT / "tests" / spec["dir"])
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)         # cocotb's runner hands this process's sys.path to the simulator, so the test files must be on it
    run_dir = str(work / "build") if lang == "vhdl" else tests_dir
    try:
        runner.test(hdl_toplevel=block, hdl_toplevel_lang=lang, test_module=spec["module"], test_dir=run_dir, build_dir=work / "build",
                    results_xml=str(results), log_file=work / "test.log",
                    extra_env={k: str(v) for k, v in config.items()})
    except SystemExit:
        pass                                  # cocotb exits non-zero when a test fails; the results file says which
    except RuntimeError:
        if not results.exists():              # the simulator stopped before any result was written
            raise RuntimeError(f"{lang} {block} stopped without results:\n{tail(work / 'test.log')}") from None
    tree = ET.parse(results)
    cases = tree.findall(".//testcase")
    failed = [c.get("name") for c in cases if c.find("failure") is not None or c.find("error") is not None]
    return len(cases), failed


def tail(path, lines=25):
    """The last lines of a log file, for error messages."""
    try:
        return "\n".join(Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "(no log)"
