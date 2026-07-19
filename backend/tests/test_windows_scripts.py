"""Runs the Windows BAT static audit (ASCII/CRLF/BOM/dangerous commands,
self-overwrite guards, unsafe call/loop patterns) as part of the normal
backend test suite, so it executes in CI and via setup_windows.bat
without any Windows- or PowerShell-specific tooling.

Also directly regression-tests two bugs that only ever surfaced on real
Windows cmd.exe:

1. "git switch overwrites the running .bat file, causing cmd.exe to
   execute stale/misaligned bytes" - once surfaced as a bare "id" being
   reported as an unrecognized command in review_pr_windows.bat.
2. "cmd /c's own /C argument parsing corrupts a quoted path that
   contains spaces once more than exactly two quote characters appear
   on the line" - once surfaced as
   'C:\\Users\\...\\Local' is not recognized as an internal or external
   command, because cmd /c "%~f0" __continue__ "%PR_NUM%" has four quote
   characters, not two, so cmd.exe falls back to stripping only the
   first and last quote on the line instead of preserving the pair
   around the path.

See the "cmd /c" comments in review_pr_windows.bat and
update_windows.bat for the full explanation of both fixes.
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


def test_review_pr_reexec_quoting_survives_cmd_c_argument_parsing() -> None:
    """cmd.exe's /C parsing only preserves a quoted path as-is when the
    command line has EXACTLY two quote characters. Quoting an extra
    argument (here, %PR_NUM%) alongside the path bumps that count to
    four, so cmd falls back to stripping only the first and last quote
    on the whole line - corrupting a spaced path like ".../Local Site
    Walk/..." into an effectively unquoted one that then gets split on
    its own spaces. Wrapping the whole "%~f0" ... expression in one more
    pair of quotes is required so that outer pair is what gets stripped,
    leaving the inner quoting intact."""
    text = _read("review_pr_windows.bat")
    assert 'cmd /c ""%~f0" __continue__ "%PR_NUM%""' in text


def test_update_reexec_quoting_survives_cmd_c_argument_parsing() -> None:
    text = _read("update_windows.bat")
    assert 'cmd /c ""%~f0" __continue_after_switch__"' in text
    assert 'cmd /c ""%~f0" __continue_after_merge__"' in text


def test_review_pr_reexecs_after_git_switch() -> None:
    """git switch -C can overwrite review_pr_windows.bat's own file with
    the PR's version. Continuing inline afterward reads stale bytes at
    the old file position - this must instead re-exec via a fresh
    cmd.exe process that reads whatever is now actually on disk. Between
    the switch and the re-exec, only the errorlevel check on the switch
    itself and comments may appear - any other command (another git
    call, echo [OK], the :post_switch label, etc.) sneaking into this
    gap would reintroduce the exact class of bug this re-exec exists to
    prevent."""
    text = _read("review_pr_windows.bat")
    switch_index = text.index('git switch -C "%PR_BRANCH%" FETCH_HEAD')
    reexec_index = text.index('cmd /c ""%~f0" __continue__')
    assert reexec_index > switch_index, (
        "the re-exec must occur after git switch -C, not before it"
    )
    non_comment = [
        line
        for line in _non_blank_lines(text, switch_index, reexec_index)
        if not line.lower().startswith("rem")
    ]
    assert non_comment == [
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
    only the errorlevel check on that git command (and comments) in
    between - any other command sneaking into either gap would
    reintroduce the exact class of bug the re-exec exists to prevent."""
    text = _read("update_windows.bat")

    switch_index = text.index('git switch "%MAIN_BRANCH%"')
    switch_reexec_index = text.index('cmd /c ""%~f0" __continue_after_switch__')
    assert switch_reexec_index > switch_index
    non_comment = [
        line
        for line in _non_blank_lines(text, switch_index, switch_reexec_index)
        if not line.lower().startswith("rem")
    ]
    assert non_comment == [
        'git switch "%MAIN_BRANCH%"',
        "if errorlevel 1 (",
        "echo [ERROR] Could not switch to %MAIN_BRANCH%.",
        "goto :fail",
        ")",
    ]

    merge_index = text.index('git merge --ff-only "origin/%MAIN_BRANCH%"')
    merge_reexec_index = text.index('cmd /c ""%~f0" __continue_after_merge__')
    assert merge_reexec_index > merge_index
    non_comment = [
        line
        for line in _non_blank_lines(text, merge_index, merge_reexec_index)
        if not line.lower().startswith("rem")
    ]
    assert non_comment == [
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
