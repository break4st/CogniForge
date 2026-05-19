# CogniForge packaging script (Windows)
# Usage:
#   .\scripts\build.ps1              # build wheel
#   .\scripts\build.ps1 -Install     # build and install locally
#   .\scripts\build.ps1 -Test        # build, install in venv, verify
#   .\scripts\build.ps1 -Clean       # remove build artifacts

param(
    [switch]$Install,
    [switch]$Test,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $ROOT

function Clean-Build {
    Write-Host "==> Cleaning build artifacts..."
    @("dist", "build", ".venv-build") | ForEach-Object {
        if (Test-Path $_) { Remove-Item -Recurse -Force $_ }
    }
    Get-ChildItem -Filter "*.egg-info" -Directory | ForEach-Object {
        Remove-Item -Recurse -Force $_.FullName
    }
    Write-Host "    done."
}

function Build-Wheel {
    Write-Host "==> Building wheel..."
    $py = (Get-Command python -ErrorAction SilentlyContinue)
    if (-not $py) { $py = (Get-Command python3 -ErrorAction SilentlyContinue) }
    if (-not $py) { Write-Host "ERROR: python not found"; exit 1 }

    & python -m pip install --quiet hatchling 2>$null
    & python -m build --wheel --no-isolation 2>&1 | Select-Object -Last 3

    $whl = Get-ChildItem dist\*.whl -ErrorAction SilentlyContinue
    if ($whl) {
        Write-Host "    wheel: $($whl.Name)"
    } else {
        Write-Host "    ERROR: wheel not found"
        exit 1
    }
}

function Verify-Wheel {
    $whl = Get-ChildItem dist\*.whl | Select-Object -First 1
    if (-not $whl) {
        Write-Host "ERROR: wheel not found"
        exit 1
    }
    Write-Host "==> Verifying: $($whl.Name)"

    $required = @(
        "cogniforge/__init__.py",
        "cogniforge/__main__.py",
        "cogniforge/cli.py",
        "cogniforge/constraints/__init__.py",
        "cogniforge/constraints/constraint_loader.py",
        "cogniforge/llm/claude_code_adapter.py",
        "cogniforge/agents/base.py",
        "cogniforge/agents/pm_agent.py",
        "cogniforge/agents/dev_agent.py"
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($whl.FullName)
    $names = $zip.Entries | ForEach-Object { $_.FullName }

    foreach ($r in $required) {
        if ($r -in $names) {
            Write-Host "    OK  $r"
        } else {
            Write-Host "    MISSING: $r"
            $zip.Dispose()
            exit 1
        }
    }
    Write-Host "    All $($required.Count) required modules present."
    Write-Host "    Total files in wheel: $($names.Count)"
    $zip.Dispose()
}

function Install-Local {
    Write-Host "==> Installing locally..."
    $whl = Get-ChildItem dist\*.whl | Select-Object -First 1
    & python -m pip install --force-reinstall $whl.FullName 2>&1 | Select-Object -Last 2
    Write-Host "    done."
    Write-Host "    CLI entry: cogniforge"
}

function Smoke-Test {
    Write-Host "==> Smoke test..."
    $venv = Join-Path $ROOT ".venv-build"

    if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
    & python -m venv $venv 2>&1 | Select-Object -Last 1

    $activate = Join-Path $venv "Scripts" "Activate.ps1"
    . $activate

    $whl = Get-ChildItem $ROOT\dist\*.whl | Select-Object -First 1
    & pip install --quiet $whl.FullName 2>&1 | Select-Object -Last 1

    # Test imports
    & python -c @"
from cogniforge.constraints import ConstraintLoader
from cogniforge.llm.claude_code_adapter import ROLE_PROMPTS
from cogniforge.agents.dev_agent import DevAgent
print('    imports OK')
"@
    if ($LASTEXITCODE -ne 0) { throw "import test failed" }

    # Test CLI entry point
    & cogniforge --help > $null 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "    cogniforge --help OK"
    } else {
        throw "CLI entry point failed"
    }

    # Test constraint defaults
    & python -c @"
from cogniforge.constraints import ConstraintLoader
from pathlib import Path
import tempfile
with tempfile.TemporaryDirectory() as d:
    loader = ConstraintLoader(d)
    loader.init_all()
    for role in ['pm','architect','design','dev','reviewer','qa','techlead','devops']:
        assert (Path(d)/'.cogniforge'/'constraints'/f'{role}.md').exists()
    print('    init_all generates 8 constraint files OK')
"@
    if ($LASTEXITCODE -ne 0) { throw "constraint test failed" }

    deactivate
    Remove-Item -Recurse -Force $venv
    Write-Host "    smoke test passed."
}

# ── main ──

if ($Clean) {
    Clean-Build
    return
}

if ($Test) {
    Clean-Build
    Build-Wheel
    Verify-Wheel
    Smoke-Test
    Write-Host ""
    Write-Host "==> Package ready: $(Get-ChildItem dist\*.whl | Select-Object -First 1)"
    return
}

if ($Install) {
    Clean-Build
    Build-Wheel
    Install-Local
    return
}

# Default: build only
Clean-Build
Build-Wheel
Verify-Wheel
Write-Host ""
Write-Host "==> Build complete. Use -Install to install, -Test for full verification."
