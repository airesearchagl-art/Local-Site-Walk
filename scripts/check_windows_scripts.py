#!/usr/bin/env python3
"""Static audit for the Windows .bat scripts and their message resources.

Runs on Linux or Windows (no PowerShell dependency) so it can be used
both locally and in Linux-based CI. Checks:

1. Every *.bat under the repo is ASCII-only (no bytes >= 0x80).
2. Every *.bat uses CRLF line endings only (no bare LF).
3. Every *.bat has no UTF-8 BOM.
4. Every *_message.txt is valid UTF-8, has no BOM, and uses CRLF only.
5. No dangerous Git commands appear as real invocations in *.bat
   (comment lines and the *_message.txt data files are not scanned,
   so mentioning these commands in explanatory text is not flagged).
6. No trailing line-continuation caret ("^"), and no caret followed by
   trailing whitespace (both corrupt cmd.exe's line joining).
7. No "call" applied to echo/set or to a bare variable reference
   (double-expansion / dynamic-command-execution hazards).
8. No "*_message.txt" resource is ever "call"ed - only "type" may be
   used to display it (calling a text file as if it were a script is
   undefined and dangerous).
9. No "for /f ... do %%X" loop whose body is just the bare loop
   variable (i.e. executing whatever a command's output happens to be,
   rather than capturing it with "set" or displaying it with "echo").
10. No "set /p" (interactive free-text input); Y/N prompts must use
    "choice /c YN" instead, which cannot receive arbitrary/malformed
    input.
11. Any file whose commands can change the repository's working tree
    ("git switch" without "-f", or "git merge --ff-only") must also
    contain a "cmd /c "%~f0"" re-exec guard. Such a file lives inside
    the repository it operates on, so the git operation can silently
    overwrite the very script that is still running - cmd.exe reads
    .bat files incrementally from disk, so continuing to execute
    in-process after the file changes underneath it reads stale,
    misaligned bytes and can run garbage commands (this exact bug
    previously surfaced as a bare "id" being "not recognized").

Exits non-zero and prints a report if any check fails.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DANGEROUS_PATTERNS = [
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\b", re.IGNORECASE),
    re.compile(r"\bgit\s+stash\b", re.IGNORECASE),
    re.compile(r"\bgit\s+checkout\s+-f\b", re.IGNORECASE),
    re.compile(r"\bgit\s+switch\s+-f\b", re.IGNORECASE),
]

# Git operations that check out/advance the working tree and can
# therefore overwrite this very script's own file on disk (with or
# without "-C" - either form replaces working-tree file contents).
SELF_MODIFYING_GIT_PATTERNS = [
    re.compile(r"\bgit\s+switch\b", re.IGNORECASE),
    re.compile(r"\bgit\s+merge\s+--ff-only\b", re.IGNORECASE),
]
# Matches "cmd /c "%~f0" ..." and the double-quote-wrapped
# "cmd /c ""%~f0" ..."" form required when extra quoted arguments follow
# (see the /C quoting comment next to each "cmd /c" call in the scripts).
REEXEC_GUARD_PATTERN = re.compile(r'cmd\s+/c\s+"+%~f0"', re.IGNORECASE)

CALL_DANGEROUS_PATTERN = re.compile(
    r"^\s*call\s+(echo\b|set\b|%[^%]+%|![^!]+!)", re.IGNORECASE
)
CALL_MESSAGE_TXT_PATTERN = re.compile(
    r"^\s*call\s+.*_message\.txt", re.IGNORECASE
)
BARE_LOOP_VAR_PATTERN = re.compile(r"\bdo\s+%%[A-Za-z]\s*$")
SET_P_PATTERN = re.compile(r"^\s*set\s+/p\b", re.IGNORECASE)


def find_bat_files() -> list[Path]:
    return sorted(REPO_ROOT.rglob("*.bat"))


def find_message_files() -> list[Path]:
    return sorted(REPO_ROOT.rglob("*_message.txt"))


def check_bat_ascii(path: Path, errors: list[str]) -> bytes:
    data = path.read_bytes()
    bad_offsets = [i for i, b in enumerate(data) if b >= 0x80]
    if bad_offsets:
        errors.append(
            f"{path.relative_to(REPO_ROOT)}: non-ASCII byte(s) at offset(s) "
            f"{bad_offsets[:5]}{'...' if len(bad_offsets) > 5 else ''} "
            f"({len(bad_offsets)} total)"
        )
    return data


def check_bat_crlf(path: Path, data: bytes, errors: list[str]) -> None:
    if data.startswith(b"\xef\xbb\xbf"):
        errors.append(f"{path.relative_to(REPO_ROOT)}: has a UTF-8 BOM (must not)")
        data = data[3:]
    # Every line must end with \r\n; a bare \n not preceded by \r is a violation.
    bare_lf = re.search(rb"(?<!\r)\n", data)
    if bare_lf:
        errors.append(
            f"{path.relative_to(REPO_ROOT)}: contains a bare LF "
            f"(line endings must be CRLF)"
        )


def check_dangerous_commands(path: Path, lines: list[str], errors: list[str]) -> None:
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        # Comment-only lines may explain why a command is NOT used.
        if stripped.lower().startswith("rem"):
            continue
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(stripped):
                errors.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: dangerous command "
                    f"detected: {stripped!r}"
                )


def check_line_continuation(path: Path, lines: list[str], errors: list[str]) -> None:
    for lineno, line in enumerate(lines, start=1):
        if line.endswith("^ ") or line.endswith("^\t"):
            errors.append(
                f"{path.relative_to(REPO_ROOT)}:{lineno}: trailing caret is "
                f"followed by whitespace (breaks line continuation)"
            )
        elif line.rstrip("\r\n").endswith("^"):
            errors.append(
                f"{path.relative_to(REPO_ROOT)}:{lineno}: line-continuation "
                f"caret found; avoid multi-line command continuation"
            )


def check_call_hazards(path: Path, lines: list[str], errors: list[str]) -> None:
    for lineno, line in enumerate(lines, start=1):
        if CALL_DANGEROUS_PATTERN.search(line):
            errors.append(
                f"{path.relative_to(REPO_ROOT)}:{lineno}: 'call' applied to "
                f"echo/set or a bare variable is a double-expansion hazard: "
                f"{line.strip()!r}"
            )
        if CALL_MESSAGE_TXT_PATTERN.search(line):
            errors.append(
                f"{path.relative_to(REPO_ROOT)}:{lineno}: a *_message.txt "
                f"resource must be shown with 'type', never 'call': "
                f"{line.strip()!r}"
            )


def check_bare_loop_variable(path: Path, lines: list[str], errors: list[str]) -> None:
    for lineno, line in enumerate(lines, start=1):
        if "for /f" in line.lower() and BARE_LOOP_VAR_PATTERN.search(line):
            errors.append(
                f"{path.relative_to(REPO_ROOT)}:{lineno}: 'for /f' loop body "
                f"executes the bare loop variable as a command instead of "
                f"capturing it with 'set' or displaying it with 'echo': "
                f"{line.strip()!r}"
            )


def check_no_set_p(path: Path, lines: list[str], errors: list[str]) -> None:
    for lineno, line in enumerate(lines, start=1):
        if SET_P_PATTERN.search(line):
            errors.append(
                f"{path.relative_to(REPO_ROOT)}:{lineno}: 'set /p' accepts "
                f"arbitrary free-text input; use 'choice /c YN' for Y/N "
                f"prompts instead: {line.strip()!r}"
            )


def check_self_modifying_reexec_guard(
    path: Path, text: str, lines: list[str], errors: list[str]
) -> None:
    has_risky_op = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("rem"):
            continue
        for pattern in SELF_MODIFYING_GIT_PATTERNS:
            if pattern.search(stripped):
                has_risky_op = True
                break
        if has_risky_op:
            break
    if has_risky_op and not REEXEC_GUARD_PATTERN.search(text):
        errors.append(
            f"{path.relative_to(REPO_ROOT)}: performs 'git switch' or "
            f"'git merge --ff-only' (which can overwrite this script's own "
            f"file on disk) without a 'cmd /c \"%~f0\"' re-exec guard "
            f"afterward - see the comment near those calls in "
            f"review_pr_windows.bat / update_windows.bat for why this is "
            f"required"
        )


def check_message_file(path: Path, errors: list[str]) -> None:
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        errors.append(f"{path.relative_to(REPO_ROOT)}: has a UTF-8 BOM (must not)")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{path.relative_to(REPO_ROOT)}: not valid UTF-8 ({exc})")
        return
    body = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
    bare_lf = re.search(rb"(?<!\r)\n", body)
    if bare_lf:
        errors.append(
            f"{path.relative_to(REPO_ROOT)}: contains a bare LF "
            f"(line endings must be CRLF)"
        )


def main() -> int:
    errors: list[str] = []

    bat_files = find_bat_files()
    if not bat_files:
        errors.append("no *.bat files found under the repository")
    for path in bat_files:
        data = check_bat_ascii(path, errors)
        check_bat_crlf(path, data, errors)
        text = data.decode("ascii", errors="replace")
        lines = text.splitlines()
        check_dangerous_commands(path, lines, errors)
        check_line_continuation(path, lines, errors)
        check_call_hazards(path, lines, errors)
        check_bare_loop_variable(path, lines, errors)
        check_no_set_p(path, lines, errors)
        check_self_modifying_reexec_guard(path, text, lines, errors)

    for path in find_message_files():
        check_message_file(path, errors)

    if errors:
        print(f"FAIL: {len(errors)} issue(s) found\n")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"OK: {len(bat_files)} .bat file(s) and message resources passed all checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
