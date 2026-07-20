"""`pytest` (コンソールスクリプト) / `python -m pytest` のどちらで起動しても
`app` パッケージを解決できることを確認する回帰テスト。

pyproject.toml の [tool.pytest.ini_options] に `pythonpath = ["."]` が
ないと、`python -m pytest` はcwdをsys.pathへ自動追加するため問題なく
動く一方、`pytest` を素のコンソールスクリプトとして直接起動した場合は
cwdが自動追加されず `ModuleNotFoundError: No module named 'app'` に
なっていた。ここではPYTHONPATHを明示的に取り除いた環境で両起動方法を
サブプロセスとして実行し、同じ結果になることを確認する。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
TARGET_TEST = "tests/test_api.py::test_health"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        cmd,
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )


def test_python_dash_m_pytest_can_import_app() -> None:
    proc = _run([sys.executable, "-m", "pytest", TARGET_TEST, "-q"])
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    assert "ModuleNotFoundError" not in output


def test_bare_pytest_command_can_import_app() -> None:
    pytest_bin = shutil.which("pytest")
    if pytest_bin is None:
        pytest.skip("pytestコンソールスクリプトがPATH上に見つからない環境")

    proc = _run([pytest_bin, TARGET_TEST, "-q"])
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    assert "ModuleNotFoundError" not in output
