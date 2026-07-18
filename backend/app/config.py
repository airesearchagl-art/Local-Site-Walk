"""アプリ設定。

実データ(動画・フレーム・生成物・メタデータ)はリポジトリ外の
データディレクトリに保存する。場所は環境変数 LSW_DATA_DIR で変更できる。
絶対パスをコードに固定しないこと。
"""

import os
from pathlib import Path

DEFAULT_DATA_DIR_NAME = "LocalSiteWalkData"

# 開発時にフロントエンド(Vite)からのアクセスを許可するオリジン。
# ローカル開発用のみ。外部オリジンを追加しないこと。
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def get_data_dir() -> Path:
    """データディレクトリを返す。

    LSW_DATA_DIR が設定されていればそれを、なければ
    ホームディレクトリ直下の LocalSiteWalkData を使う。
    """
    raw = os.environ.get("LSW_DATA_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / DEFAULT_DATA_DIR_NAME
