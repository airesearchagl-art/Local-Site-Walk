"""Regression test for the StarletteDeprecationWarning that fired when
`starlette.testclient` fell back to `httpx` instead of the preferred
`httpx2` package ("Using `httpx` with `starlette.testclient` is
deprecated; install `httpx2` instead.").

The import is run in a fresh subprocess rather than the current pytest
process: Python's default warning filter only shows a given warning once
per (message, category, module, lineno), so if this test ran in-process
after another test module had already imported `fastapi.testclient`, the
warning would not fire again here even if the underlying cause (a missing
or reverted `httpx2` dependency) returned.
"""

import subprocess
import sys


def test_importing_testclient_does_not_emit_deprecation_warning() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import warnings; warnings.simplefilter('error'); "
            "from fastapi.testclient import TestClient",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
