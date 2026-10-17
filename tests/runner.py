"""Build one circuit for one simulator and run its cocotb tests.

Used by the regression tests (tests/test_regression.py) and by the mutation checker (tools/mutate.py).
Verilog runs on Icarus Verilog, VHDL on GHDL; the Python tests in tests/uart are the same for both.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

from cocotb_tools.runner import get_runner

ROOT = Path(__file__).resolve().parents[1]
SIMULATOR = {"verilog": "icarus", "vhdl": "ghdl"}
EXTENSION = {"verilog": ".v", "vhdl": ".vhd"}
BIT_RATES = [8, 32]                          # clock cycles per bit that every block is run at
BLOCKS = {                                   # toplevel -> (files needed, cocotb test module)
    "uart_tx": (["uart_tx"], "test_uart_tx"),
    "uart_rx": (["uart_rx"], "test_uart_rx"),
    "uart_loop": (["uart_tx", "uart_rx", "uart_loop"], "test_uart_loop"),
}


def run(lang, block, clks, work_dir, rtl_dir=None):
    """Build `block` in `lang` with CLKS_PER_BIT = clks and run its tests.

    Returns (number of tests run, [names of the tests that failed]). A circuit that does not build raises an exception.
    """
    rtl_dir = Path(rtl_dir) if rtl_dir else ROOT / "rtl" / lang
    files, module = BLOCKS[block]
    sources = [rtl_dir / f"{f}{EXTENSION[lang]}" for f in files]
    work = Path(work_dir)
    runner = get_runner(SIMULATOR[lang])
    work.mkdir(parents=True, exist_ok=True)
    try:
        runner.build(sources=sources, hdl_toplevel=block, parameters={"CLKS_PER_BIT": clks}, build_dir=work / "build", always=True,
                     timescale=("1ns", "1ps"),           # Icarus would otherwise simulate with a time precision of one second
                     log_file=work / "build.log")
    except Exception as e:                               # noqa: BLE001
        raise RuntimeError(f"{lang} {block} did not build:\n{tail(work / 'build.log')}") from e
    results = work / "results.xml"
    # GHDL's LLVM backend looks for the elaborated program in the folder it runs in, so VHDL runs in the build folder and is
    # told where the Python test files are; Icarus Verilog runs from the test folder.
    tests_dir = str(ROOT / "tests" / "uart")
    run_dir = str(work / "build") if lang == "vhdl" else tests_dir
    try:
        runner.test(hdl_toplevel=block, hdl_toplevel_lang=lang, test_module=module, test_dir=run_dir, build_dir=work / "build",
                    results_xml=str(results), log_file=work / "test.log",
                    extra_env={"CLKS_PER_BIT": str(clks), "PYTHONPATH": tests_dir})
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
