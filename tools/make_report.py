#!/usr/bin/env python3
"""tools/make_report.py - write the "Results" part of the README from the tests and from results/mutation.json.

    python3 tools/make_report.py            rewrite the block between <!-- results:start --> and <!-- results:end -->
    python3 tools/make_report.py --check    exit 1 if the README is out of date (a test runs this)

No number in that block is typed in: the tests are counted in the test files, the bit rates and blocks come from tests/runner.py, and the
mutation results come from the file that tools/mutate.py writes.
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))
from mutate import MUTATIONS  # noqa: E402
from runner import BIT_RATES, BLOCKS  # noqa: E402

README = ROOT / "README.md"
START, END = "<!-- results:start -->", "<!-- results:end -->"


def cocotb_tests(module):
    """[(name, one-line description)] of the @cocotb.test functions in tests/uart/<module>.py, in file order."""
    tree = ast.parse((ROOT / "tests" / "uart" / f"{module}.py").read_text(encoding="utf-8"))
    out = []
    for n in tree.body:
        if isinstance(n, ast.AsyncFunctionDef) and any("test" in ast.unparse(d) and "cocotb" in ast.unparse(d) for d in n.decorator_list):
            doc = " ".join((ast.get_docstring(n) or "").split())
            out.append((n.name, doc))
    return out


def render():
    data = json.loads((ROOT / "results" / "mutation.json").read_text(encoding="utf-8"))
    by_id = {}
    for m in data["mutants"]:
        by_id.setdefault(m["id"], {})[m["language"]] = m["result"]
    total = len(data["mutants"])
    killed = sum(1 for m in data["mutants"] if m["result"] == "killed")
    survived = sum(1 for m in data["mutants"] if m["result"] == "survived")
    blocks = list(BLOCKS)
    n_tests = {b: len(cocotb_tests(BLOCKS[b][1])) for b in blocks}
    runs = 2 * len(blocks) * len(BIT_RATES)
    out = [START, "", "### Results", "",
           f"Every block is built and run in both languages at {' and '.join(str(r) for r in BIT_RATES)} clock cycles per bit: **{runs} simulator runs** per push "
           f"(2 languages x {len(blocks)} blocks x {len(BIT_RATES)} bit rates). The tests, which are the same Python for Verilog and VHDL:", ""]
    for b in blocks:
        out += [f"**`{b}`**: {n_tests[b]} test{'' if n_tests[b] == 1 else 's'}", ""]
        out += [f"- `{name}`: {doc}" for name, doc in cocotb_tests(BLOCKS[b][1])] + [""]
    out += ["### Breaking the circuits on purpose", "",
            f"`tools/mutate.py` makes {len(MUTATIONS)} realistic bugs, one at a time, in each language, and runs the block's tests against each broken circuit. "
            f"Of {total} broken circuits, **{killed} were caught** by at least one failing test and **{survived} survived**.", "",
            "| Bug | Verilog | VHDL |", "|---|---|---|"]
    for mid, what, _, _, _, undetectable in MUTATIONS:
        r = by_id.get(mid, {})
        cell = lambda lang: {"killed": "caught", "survived": "**survived**", "error": "**error**"}.get(r.get(lang), "not run")   # noqa: E731
        out.append(f"| {what} | {cell('verilog')} | {cell('vhdl')} |")
    for mid, what, _, _, _, undetectable in MUTATIONS:
        if undetectable:
            out += ["", f"The surviving bug (\"{what}\") is **expected** to survive, because it cannot be detected in RTL simulation: {undetectable}."]
    out += ["", END]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if the README is out of date")
    a = ap.parse_args(argv)
    text = README.read_text(encoding="utf-8").replace("\r\n", "\n")
    if START not in text or END not in text:
        print(f"STOP: README.md has no {START} ... {END} markers", file=sys.stderr)
        return 2
    new = text[:text.index(START)] + render() + text[text.index(END) + len(END):]
    if a.check:
        if new != text:
            print("README.md is out of date: run  python3 tools/make_report.py", file=sys.stderr)
            return 1
        print("README.md is up to date")
        return 0
    if new == text:
        print("README.md already up to date")
    else:
        README.write_text(new, encoding="utf-8", newline="\n")
        print("README.md updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
