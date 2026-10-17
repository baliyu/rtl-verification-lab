"""Checks that need no simulator: the README's results block is current, and the recorded mutation results are complete and as expected."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_readme_results_block_is_current():
    """The results block in the README is exactly what tools/make_report.py writes from the tests and results/mutation.json."""
    r = subprocess.run([sys.executable, "tools/make_report.py", "--check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr + r.stdout


def test_the_recorded_mutation_results_cover_every_mutation_in_both_languages_and_are_as_expected():
    """results/mutation.json lists every mutation in tools/mutate.py for both languages; all are caught except the ones listed as undetectable, which survive."""
    sys.path.insert(0, str(ROOT / "tools"))
    from mutate import MUTATIONS
    data = json.loads((ROOT / "results" / "mutation.json").read_text(encoding="utf-8"))
    got = {(m["id"], m["language"]): m["result"] for m in data["mutants"]}
    assert set(got) == {(m[0], lang) for m in MUTATIONS for lang in ("verilog", "vhdl")}
    expected_survivors = {m[0] for m in MUTATIONS if m[5]}
    assert set(data["expected_survivors"]) == expected_survivors
    for (mid, lang), result in got.items():
        assert result == ("survived" if mid in expected_survivors else "killed"), f"{mid} ({lang}): {result}"
