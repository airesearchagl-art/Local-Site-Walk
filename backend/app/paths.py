"""パス安全性ヘルパー。

管理対象ディレクトリ(サムネイル保存先・案件フォルダ)の外へ、symlinkや
``..``、絶対パス指定などで脱出できないようにするための共通処理。
"""

from pathlib import Path


def resolve_safe(path: Path) -> Path | None:
    """symlinkを解決した絶対パスを返す。解決に失敗した場合はNoneを返す。

    循環symlinkなど、OS側が解決に失敗するケースを例外を投げずに
    「安全でない」と呼び出し側へ伝えるためのラッパー。
    """
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None


def is_within(candidate: Path, root: Path) -> bool:
    """resolve済みcandidateが、resolve済みroot自身またはroot配下にあるか。

    candidate/rootとも事前にresolve_safe()を通した絶対パスであることを
    前提とする。Windowsのドライブ違いなど relative_to が ValueError を
    投げるケースはここで吸収してFalseを返す。
    """
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def safe_unlink_within(path_str: str | None, root: Path) -> bool:
    """rootの配下にあるファイルだけを削除する。

    相対パス・``..``・絶対パスでのroot外指定・symlinkやWindows
    junction経由でroot外へ解決されるパスは削除せず、Falseを返す
    安全なno-opとする(明示的な例外は投げない)。削除できた場合はTrue。
    """
    if not path_str:
        return False
    candidate = Path(path_str)
    if not candidate.is_absolute():
        return False

    resolved_root = resolve_safe(root)
    resolved_candidate = resolve_safe(candidate)
    if resolved_root is None or resolved_candidate is None:
        return False
    if not is_within(resolved_candidate, resolved_root):
        return False

    # 判定後にcandidateの実体が差し替わるTOCTOUの余地は理論上残るが、
    # 本アプリはローカル単一ユーザー前提(CLAUDE.md)であり、データ
    # ディレクトリへ同時に書き込む未信頼な他プロセスは想定しない。
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        return False
    return True
