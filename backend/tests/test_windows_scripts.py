"""Runs the Windows BAT static audit (ASCII/CRLF/BOM/dangerous commands)
as part of the normal backend test suite, so it executes in CI and via
setup_windows.bat without any Windows- or PowerShell-specific tooling.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "check_windows_scripts.py"


def test_windows_scripts_pass_static_audit() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"scripts/check_windows_scripts.py failed:\n{result.stdout}{result.stderr}"
    )
