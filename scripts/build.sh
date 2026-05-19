#!/usr/bin/env bash
# CogniForge packaging script
# Usage:
#   ./scripts/build.sh              # build wheel
#   ./scripts/build.sh --install    # build and install locally
#   ./scripts/build.sh --test       # build, install in venv, verify
#   ./scripts/build.sh --clean      # remove build artifacts

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

clean() {
    echo "==> Cleaning build artifacts..."
    rm -rf dist/ build/ *.egg-info src/*.egg-info .venv-build/
    echo "    done."
}

build_wheel() {
    echo "==> Building wheel..."
    /usr/local/bin/python3.11 -m pip install --quiet hatchling 2>/dev/null || true
    /usr/local/bin/python3.11 -m build --wheel --no-isolation 2>&1 | tail -3
    echo "    wheel: $(ls -1 dist/*.whl 2>/dev/null || echo 'MISSING')"
}

verify_wheel() {
    local whl=$(ls -1 dist/*.whl 2>/dev/null | head -1)
    if [ -z "$whl" ]; then
        echo "ERROR: wheel not found"
        exit 1
    fi
    echo "==> Verifying: $(basename $whl)"
    /usr/local/bin/python3.11 -c "
import zipfile, sys
z = zipfile.ZipFile('$whl')
names = z.namelist()

# Check key modules exist
required = [
    'cogniforge/__init__.py',
    'cogniforge/__main__.py',
    'cogniforge/cli.py',
    'cogniforge/constraints/__init__.py',
    'cogniforge/constraints/constraint_loader.py',
    'cogniforge/llm/claude_code_adapter.py',
    'cogniforge/agents/base.py',
    'cogniforge/agents/pm_agent.py',
    'cogniforge/agents/dev_agent.py',
]
for r in required:
    assert r in names, f'MISSING: {r}'
    print(f'    OK  {r}')
print(f'    All {len(required)} required modules present.')
print(f'    Total files in wheel: {len(names)}')
"
}

install_local() {
    echo "==> Installing locally..."
    /usr/local/bin/python3.11 -m pip install --force-reinstall dist/*.whl 2>&1 | tail -2
    echo "    done."
    echo "    CLI entry: $(which cogniforge 2>/dev/null || echo 'check with: python3.11 -m cogniforge')"
}

smoke_test() {
    echo "==> Smoke test..."
    local venv="$ROOT/.venv-build"
    /usr/local/bin/python3.11 -m venv "$venv" --clear 2>&1 | tail -1
    source "$venv/bin/activate"
    pip install --quiet "$ROOT"/dist/*.whl 2>&1 | tail -1

    # Test import
    python -c "
from cogniforge.constraints import ConstraintLoader
from cogniforge.llm.claude_code_adapter import ROLE_PROMPTS
from cogniforge.agents.dev_agent import DevAgent
print('    imports OK')
"

    # Test CLI entry point
    cogniforge --help > /dev/null 2>&1 && echo "    cogniforge --help OK"

    # Test constraint defaults
    python -c "
from cogniforge.constraints import ConstraintLoader
from pathlib import Path
import tempfile
with tempfile.TemporaryDirectory() as d:
    loader = ConstraintLoader(d)
    loader.init_all()
    for role in ['pm','architect','design','dev','reviewer','qa','techlead','devops']:
        assert (Path(d)/'.cogniforge'/'constraints'/f'{role}.md').exists()
    print('    init_all generates 8 constraint files OK')
"

    deactivate
    rm -rf "$venv"
    echo "    smoke test passed."
}

# ── main ──

case "${1:-}" in
    --clean)
        clean
        ;;
    --install)
        clean
        build_wheel
        install_local
        ;;
    --test)
        clean
        build_wheel
        verify_wheel
        smoke_test
        echo ""
        echo "==> Package ready: $(ls dist/*.whl)"
        ;;
    *)
        clean
        build_wheel
        verify_wheel
        echo ""
        echo "==> Build complete. Use --install to install, --test for full verification."
        ;;
esac
