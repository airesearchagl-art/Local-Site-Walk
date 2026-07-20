"""動画フォルダの再帰探索。

``Path.rglob()`` はsymlinkディレクトリを追従するため、登録フォルダの外を
意図せず探索したり、循環symlinkで無限に辿ったりする恐れがある。ここでは
実体パス(resolve後)を訪問済み集合で追跡しながら手動で走査し、symlink
ディレクトリには原則として入らない。
"""

from collections.abc import Iterator
from pathlib import Path

from . import paths


def iter_scan_candidates(root: Path) -> Iterator[Path]:
    """root配下の通常ファイルを列挙する(symlinkディレクトリは追従しない)。

    - symlinkディレクトリには入らない(原則として追従しない)
    - symlinkファイルは、解決後の実体がroot配下の場合のみ列挙する
    - 実体パスを訪問済み集合で追跡するため、Windows junctionなど
      is_symlink()で検出できないreparse pointによる循環参照があっても
      無限探索にはならない
    - root外へ解決されるパス(symlink/junction経由を含む)は列挙しない
    """
    resolved_root = paths.resolve_safe(root)
    if resolved_root is None:
        return

    visited: set[Path] = set()
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        resolved_current = paths.resolve_safe(current)
        if resolved_current is None or resolved_current in visited:
            continue
        if not paths.is_within(resolved_current, resolved_root):
            continue
        visited.add(resolved_current)

        try:
            entries = list(current.iterdir())
        except OSError:
            continue

        for entry in entries:
            if entry.is_symlink():
                if entry.is_dir():
                    # 原則としてsymlinkディレクトリは追従しない
                    continue
                if entry.is_file():
                    resolved_entry = paths.resolve_safe(entry)
                    if resolved_entry is not None and paths.is_within(
                        resolved_entry, resolved_root
                    ):
                        yield entry
                continue
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file():
                yield entry
