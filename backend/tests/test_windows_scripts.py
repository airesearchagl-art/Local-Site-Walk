"""Runs the Windows BAT static audit (ASCII/CRLF/BOM/dangerous commands,
self-overwrite guards, unsafe call/loop patterns) as part of the normal
backend test suite, so it executes in CI and via setup_windows.bat
without any Windows- or PowerShell-specific tooling.

Also directly regression-tests the specific "git switch overwrites the
running .bat file, causing cmd.exe to execute stale/misaligned bytes"
bug that once surfaced as a bare "id" being reported as an unrecognized
command in review_pr_windows.bat (see the "cmd /c "%~f0"" re-exec guard
comments in review_pr_windows.bat and update_windows.bat).
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "check_windows_scripts.py"
SCRIPTS_DIR = REPO_ROOT / "scripts"


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


def _read(name: str) -> str:
    path = SCRIPTS_DIR / name
    return path.read_bytes().decode("ascii")


def _non_blank_lines(text: str, start: int, end: int) -> list[str]:
    return [
        line.strip()
        for line in text[start:end].splitlines()
        if line.strip()
    ]


def test_review_pr_reexecs_after_git_switch() -> None:
    """git switch -C can overwrite review_pr_windows.bat's own file with
    the PR's version. Continuing inline afterward reads stale bytes at
    the old file position - this must instead re-exec via a fresh
    cmd.exe process that reads whatever is now actually on disk. Only
    the errorlevel check on the switch itself may run in between - any
    other command (another git call, echo [OK], the :post_switch label,
    etc.) sneaking into this gap would reintroduce the exact class of
    bug this re-exec exists to prevent."""
    text = _read("review_pr_windows.bat")
    switch_index = text.index('git switch -C "%PR_BRANCH%" FETCH_HEAD')
    reexec_index = text.index('cmd /c "%~f0" __continue__')
    assert reexec_index > switch_index, (
        "the re-exec must occur after git switch -C, not before it"
    )
    assert _non_blank_lines(text, switch_index, reexec_index) == [
        'git switch -C "%PR_BRANCH%" FETCH_HEAD',
        "if errorlevel 1 (",
        "echo [ERROR] Could not switch branch.",
        "goto :fail",
        ")",
    ]


def test_review_pr_continue_marker_is_the_first_branch_taken() -> None:
    """The __continue__ re-entry check must be evaluated before any
    other argument parsing, so the fresh process jumps straight to
    :post_switch instead of re-running (and possibly re-failing) the
    original PR-number validation."""
    text = _read("review_pr_windows.bat")
    marker_index = text.index('"%~1"=="__continue__"')
    pr_num_validation_index = text.index('findstr /r "^[0-9][0-9]*$"')
    assert marker_index < pr_num_validation_index


def test_update_reexecs_after_switch_and_after_merge() -> None:
    """Both git switch (to main) and git merge --ff-only can overwrite
    update_windows.bat's own file, so each needs its own re-exec, with
    only the errorlevel check on that git command in between - any other
    command sneaking into either gap would reintroduce the exact class
    of bug the re-exec exists to prevent."""
    text = _read("update_windows.bat")

    switch_index = text.index('git switch "%MAIN_BRANCH%"')
    switch_reexec_index = text.index('cmd /c "%~f0" __continue_after_switch__')
    assert switch_reexec_index > switch_index
    assert _non_blank_lines(text, switch_index, switch_reexec_index) == [
        'git switch "%MAIN_BRANCH%"',
        "if errorlevel 1 (",
        "echo [ERROR] Could not switch to %MAIN_BRANCH%.",
        "goto :fail",
        ")",
    ]

    merge_index = text.index('git merge --ff-only "origin/%MAIN_BRANCH%"')
    merge_reexec_index = text.index('cmd /c "%~f0" __continue_after_merge__')
    assert merge_reexec_index > merge_index
    assert _non_blank_lines(text, merge_index, merge_reexec_index) == [
        'git merge --ff-only "origin/%MAIN_BRANCH%"',
        "if errorlevel 1 (",
        'type "%~dp0update_diverged_message.txt"',
        "goto :done",
        ")",
    ]


def test_no_bat_uses_set_p_for_yes_no_prompts() -> None:
    """set /p accepts arbitrary free-text; Y/N prompts must use
    'choice /c YN' so malformed/unexpected input cannot occur."""
    for path in sorted(REPO_ROOT.rglob("*.bat")):
        text = path.read_bytes().decode("ascii")
        assert "set /p" not in text.lower().replace("  ", " "), (
            f"{path.relative_to(REPO_ROOT)} still uses set /p; use choice /c YN"
        )


def test_no_bat_calls_a_message_txt_file() -> None:
    """*_message.txt files must only ever be displayed with 'type'; using
    'call' on them would attempt to execute them as a batch script."""
    for path in sorted(REPO_ROOT.rglob("*.bat")):
        text = path.read_bytes().decode("ascii")
        for line in text.splitlines():
            stripped = line.strip().lower()
            if stripped.startswith("call") and "_message.txt" in stripped:
                raise AssertionError(
                    f"{path.relative_to(REPO_ROOT)}: {line.strip()!r}"
                )
