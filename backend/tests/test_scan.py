from pathlib import Path

import pytest

from app.scan import iter_scan_candidates


def _names(root: Path) -> set[str]:
    # as_posix() (not str()) so assertions comparing against "sub/x.mp4"
    # literals don't depend on the OS path separator - str(WindowsPath)
    # uses "\", which made this comparison fail on Windows even though
    # iter_scan_candidates() itself found the correct files.
    return {p.relative_to(root).as_posix() for p in iter_scan_candidates(root)}


def test_iter_scan_candidates_finds_regular_nested_files(tmp_path: Path) -> None:
    root = tmp_path / "videos"
    root.mkdir()
    (root / "walk1.mp4").write_bytes(b"x")
    sub = root / "sub"
    sub.mkdir()
    (sub / "walk2.mp4").write_bytes(b"x")

    assert _names(root) == {"walk1.mp4", "sub/walk2.mp4"}


def test_iter_scan_candidates_does_not_follow_symlink_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "videos"
    root.mkdir()
    (root / "walk1.mp4").write_bytes(b"x")

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.mp4").write_bytes(b"x")

    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"この環境ではsymlinkを作成できません: {exc}")

    assert _names(root) == {"walk1.mp4"}


def test_iter_scan_candidates_rejects_symlink_file_escaping_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "videos"
    root.mkdir()
    (root / "walk1.mp4").write_bytes(b"x")

    outside = tmp_path / "outside"
    outside.mkdir()
    outside_video = outside / "secret.mp4"
    outside_video.write_bytes(b"x")

    link = root / "escape.mp4"
    try:
        link.symlink_to(outside_video)
    except OSError as exc:
        pytest.skip(f"この環境ではsymlinkを作成できません: {exc}")

    assert _names(root) == {"walk1.mp4"}


def test_iter_scan_candidates_allows_symlink_file_resolving_within_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "videos"
    root.mkdir()
    sub = root / "sub"
    sub.mkdir()
    real = sub / "real.mp4"
    real.write_bytes(b"x")

    link = root / "alias.mp4"
    try:
        link.symlink_to(real)
    except OSError as exc:
        pytest.skip(f"この環境ではsymlinkを作成できません: {exc}")

    assert _names(root) == {"sub/real.mp4", "alias.mp4"}


def test_iter_scan_candidates_terminates_on_circular_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "videos"
    root.mkdir()
    (root / "walk1.mp4").write_bytes(b"x")

    loop = root / "loop"
    try:
        loop.symlink_to(root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"この環境ではsymlinkを作成できません: {exc}")

    # 無限探索にならず終了し、通常ファイルの結果は変わらないこと。
    assert _names(root) == {"walk1.mp4"}


def test_iter_scan_candidates_on_missing_root_yields_nothing(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "does-not-exist"
    assert list(iter_scan_candidates(missing_root)) == []
