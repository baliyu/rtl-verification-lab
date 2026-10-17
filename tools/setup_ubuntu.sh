#!/usr/bin/env bash
# tools/setup_ubuntu.sh - install what the tests need on Ubuntu 24.04 (also WSL2): Icarus Verilog, GHDL (LLVM backend),
# and a Python environment with cocotb and pytest.
#
#   bash tools/setup_ubuntu.sh                run once on your machine (asks for your password: it uses sudo)
#   bash tools/setup_ubuntu.sh --system-only  only the simulators; used by CI, which installs the Python packages itself
set -euo pipefail

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq iverilog ghdl-llvm libllvm18

# Ubuntu 24.04 packaging quirk: ghdl-llvm looks for libLLVM-18.so.18.1, and the libllvm18 package ships it as libLLVM.so.18.1.
need=/usr/lib/x86_64-linux-gnu/libLLVM-18.so.18.1
have=/usr/lib/llvm-18/lib/libLLVM.so.18.1
if [ ! -e "$need" ] && [ -e "$have" ]; then
  $SUDO ln -s "$have" "$need"
  echo "linked $need -> $have"
fi
if ldd /usr/lib/ghdl/llvm/ghdl1-llvm 2>/dev/null | grep -q "not found"; then
  echo "STOP: GHDL still has a missing library:"; ldd /usr/lib/ghdl/llvm/ghdl1-llvm | grep "not found"; exit 1
fi
echo "Icarus Verilog: $(iverilog -V 2>&1 | head -1)"
echo "GHDL:           $(ghdl --version | head -1)"

if [ "${1:-}" != "--system-only" ]; then
  ENV="$HOME/.venvs/rtl-verification-lab"
  python3 -m venv "$ENV"
  "$ENV/bin/python" -m pip install -q -r "$(cd "$(dirname "$0")/.." && pwd)/requirements.txt"
  echo "Python environment: $ENV  (activate it with:  source $ENV/bin/activate)"
fi
