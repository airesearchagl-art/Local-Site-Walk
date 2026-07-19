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


def check_dangerous_commands(path: Path, data: bytes, errors: list[str]) -> None:
    text = data.decode("ascii", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
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
        check_dangerous_commands(path, data, errors)

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
