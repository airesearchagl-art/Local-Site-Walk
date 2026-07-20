from pathlib import Path

import pytest

from app import paths


def test_safe_unlink_within_deletes_file_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "thumbnails"
    root.mkdir()
    target = root / "1.jpg"
    target.write_bytes(b"jpeg-bytes")

    assert paths.safe_unlink_within(str(target), root) is True
    assert not target.exists()


def test_safe_unlink_within_missing_file_inside_root_is_not_an_error(
    tmp_path: Path,
) -> None:
    root = tmp_path / "thumbnails"
    root.mkdir()
    missing = root / "does-not-exist.jpg"

    # 既存API契約(unlink(missing_ok=True))と同じく、root配下を指す限り
    # 実体が既になくても例外を投げず、削除試行は成功扱いとする。
    assert paths.safe_unlink_within(str(missing), root) is True


def test_safe_unlink_within_rejects_file_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "thumbnails"
    root.mkdir()
    outside_dir = tmp_path / "private"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.jpg"
    outside_file.write_bytes(b"do-not-delete")

    assert paths.safe_unlink_within(str(outside_file), root) is False
    assert outside_file.exists()


def test_safe_unlink_within_rejects_dotdot_traversal(tmp_path: Path) -> None:
    root = tmp_path / "thumbnails"
    root.mkdir()
    outside_file = tmp_path / "escape.jpg"
    outside_file.write_bytes(b"do-not-delete")

    traversal_path = str(root / ".." / "escape.jpg")
    assert paths.safe_unlink_within(traversal_path, root) is False
    assert outside_file.exists()


def test_safe_unlink_within_rejects_relative_path(tmp_path: Path) -> None:
    root = tmp_path / "thumbnails"
    root.mkdir()
    target = root / "1.jpg"
    target.write_bytes(b"jpeg-bytes")

    assert paths.safe_unlink_within("1.jpg", root) is False
    assert target.exists()


def test_safe_unlink_within_rejects_empty_or_none(tmp_path: Path) -> None:
    root = tmp_path / "thumbnails"
    root.mkdir()

    assert paths.safe_unlink_within(None, root) is False
    assert paths.safe_unlink_within("", root) is False


def test_safe_unlink_within_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "thumbnails"
    root.mkdir()
    outside_dir = tmp_path / "private"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.jpg"
    outside_file.write_bytes(b"do-not-delete")

    link = root / "evil_link"
    try:
        link.symlink_to(outside_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"この環境ではsymlinkを作成できません: {exc}")

    escaping_path = str(link / "secret.jpg")
    assert paths.safe_unlink_within(escaping_path, root) is False
    assert outside_file.exists()


def test_is_within_allows_root_itself(tmp_path: Path) -> None:
    root = tmp_path / "thumbnails"
    root.mkdir()
    assert paths.is_within(root, root) is True


def test_is_within_rejects_sibling_directory(tmp_path: Path) -> None:
    root = tmp_path / "thumbnails"
    root.mkdir()
    sibling = tmp_path / "thumbnails-evil"
    sibling.mkdir()
    assert paths.is_within(sibling, root) is False
