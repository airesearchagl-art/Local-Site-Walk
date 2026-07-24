"""Windows専用のpath safety検証。

junction(NTFS reparse point)・大文字小文字非区別・Windows固有のresolve
挙動は、Linux上のsymlinkでは代替できない(is_symlink()の検出可否が
POSIX symlinkとWindows junctionで異なるため)。このモジュールは
windows-latest CI runner上でのみ実行し、それ以外のプラットフォームでは
収集時にskipする(プラットフォーム都合のskipであり、権限不足による
skipとは区別する)。

symlink作成にはWindowsの追加権限(Developer Mode / SeCreateSymbolicLink
Privilege)が必要な場合があるため、symlink系の一部だけ権限不足時に理由を
明示してskipしてよい。junction(mklink /J)はこの追加権限を必要としない
ため、作成自体が失敗した場合はskipせずテストを失敗させ、
stderr/returncodeを含めて原因を明らかにする。
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.paths import safe_unlink_within
from app.scan import iter_scan_candidates

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows専用テスト(junction/NTFS固有挙動の検証のため)",
)


def _create_junction(link: Path, target: Path) -> None:
    """mklink /J でjunctionを作成する。

    junction作成はWindowsの追加権限(symlink用のDeveloper Mode等)を必要と
    しないため、失敗した場合は権限不足によるskip対象にせず、原因(stderr/
    returncode)を含めてテストを失敗させる。
    """
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            "junction作成に失敗しました(mklink /Jは追加権限を必要としない"
            "ため、権限不足によるskip対象にしない)。"
            f" returncode={result.returncode}"
            f" stdout={result.stdout!r} stderr={result.stderr!r}"
        )


def _create_symlink_or_skip(
    link: Path, target: Path, *, target_is_directory: bool = False
) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        pytest.skip(
            "この環境ではsymlinkを作成できません(Developer Mode / "
            f"SeCreateSymbolicLinkPrivilege不足の可能性): {exc!r}"
        )


def test_windows_junction_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.mp4"
    secret.write_bytes(b"do-not-touch")

    link = root / "escape_junction"
    _create_junction(link, outside)

    names = {str(p.relative_to(root)) for p in iter_scan_candidates(root)}

    assert not any(name.startswith("escape_junction") for name in names)
    assert secret.exists()
    assert secret.read_bytes() == b"do-not-touch"


def test_windows_junction_target_is_not_deleted(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.jpg"
    secret.write_bytes(b"do-not-delete")

    link = root / "escape_junction"
    _create_junction(link, outside)

    escaping_path = str(link / "secret.jpg")
    assert safe_unlink_within(escaping_path, root) is False
    assert secret.exists()
    assert secret.read_bytes() == b"do-not-delete"


def test_windows_case_variation_cannot_bypass_root(tmp_path: Path) -> None:
    root = tmp_path / "CaseSensitiveLookingRoot"
    root.mkdir()
    target = root / "1.jpg"
    target.write_bytes(b"jpeg")

    # NTFSは既定でcase-insensitiveなため、rootと大文字小文字だけが異なる
    # 表記でも同じ実体を指すはず。誤ってroot外と判定されて削除できない、
    # という過剰な境界になっていないことを確認する。
    differently_cased_same_file = str(root).swapcase() + "\\1.jpg"
    assert safe_unlink_within(differently_cased_same_file, root) is True
    assert not target.exists()

    # rootとは別物の "root名+suffix" ディレクトリを大文字小文字を変えた
    # 表記で参照しても、root配下として誤って許可されない(prefix衝突が
    # case変化によってすり抜けられない)ことを確認する。
    evil_root = tmp_path / (root.name + "-evil")
    evil_root.mkdir()
    evil_secret = evil_root / "secret.jpg"
    evil_secret.write_bytes(b"do-not-delete")

    cased_evil_path = str(evil_root).swapcase() + "\\" + evil_secret.name
    assert safe_unlink_within(cased_evil_path, root) is False
    assert evil_secret.exists()


def test_windows_prefix_collision_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    evil = tmp_path / "root-evil"
    evil.mkdir()
    secret = evil / "secret.jpg"
    secret.write_bytes(b"do-not-delete")

    assert safe_unlink_within(str(secret), root) is False
    assert secret.exists()
    assert secret.read_bytes() == b"do-not-delete"


def test_windows_broken_link_is_safe(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    # broken junction: 作成後にtarget実体を削除し、dangling状態を作る。
    junction_target = tmp_path / "junction_target"
    junction_target.mkdir()
    junction = root / "broken_junction"
    _create_junction(junction, junction_target)
    shutil.rmtree(junction_target)

    try:
        names = {str(p.relative_to(root)) for p in iter_scan_candidates(root)}
    except OSError as exc:
        pytest.fail(f"broken junctionの走査で例外が発生しました: {exc!r}")
    assert not any(name.startswith("broken_junction") for name in names)

    try:
        result = safe_unlink_within(str(junction / "ghost.jpg"), root)
    except OSError as exc:
        pytest.fail(f"broken junction配下の削除試行で例外が発生しました: {exc!r}")
    assert result is False

    # broken symlink: symlink作成権限が不足する場合のみ理由を明示してskip。
    broken_symlink = root / "broken_symlink.jpg"
    nonexistent = tmp_path / "does_not_exist" / "ghost.jpg"
    _create_symlink_or_skip(broken_symlink, nonexistent)

    try:
        result2 = safe_unlink_within(str(broken_symlink), root)
    except OSError as exc:
        pytest.fail(f"broken symlinkの削除試行で例外が発生しました: {exc!r}")
    assert result2 is False
