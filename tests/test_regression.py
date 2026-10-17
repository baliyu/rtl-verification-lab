"""Run every block on both simulators at each of its settings: Verilog on Icarus Verilog, VHDL on GHDL, with the same Python tests."""
import pytest

from runner import BLOCKS, describe, run

CASES = [(lang, block, config) for lang in ("verilog", "vhdl") for block, spec in BLOCKS.items() for config in spec["configs"]]


@pytest.mark.parametrize("lang,block,config", CASES, ids=[f"{lang}-{block}-" + "-".join(f"{k}={v}" for k, v in config.items()) for lang, block, config in CASES])
def test_circuit(lang, block, config, tmp_path):
    ran, failed = run(lang, block, config, tmp_path)
    assert ran > 0, "no tests ran"
    assert not failed, f"{lang} {block} with {describe(config)}: failed {failed}"
