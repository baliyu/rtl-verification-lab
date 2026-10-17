"""Run every UART block on both simulators at two bit rates: Verilog on Icarus Verilog, VHDL on GHDL, with the same Python tests."""
import pytest

from runner import BIT_RATES, BLOCKS, run


@pytest.mark.parametrize("clks", BIT_RATES)
@pytest.mark.parametrize("block", list(BLOCKS))
@pytest.mark.parametrize("lang", ["verilog", "vhdl"])
def test_circuit(lang, block, clks, tmp_path):
    ran, failed = run(lang, block, clks, tmp_path)
    assert ran > 0, "no tests ran"
    assert not failed, f"{lang} {block} with {clks} clocks per bit: failed {failed}"
