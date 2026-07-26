"""配布用の単体 HTML を生成する。

歳時記・有名句コーパス・読み辞書をテンプレートに埋め込み、外部通信なしで動く
1 ファイルの HTML を書き出す。ブラウザ内で完結するため、LLM 評価と Web 検索は
載らない（そちらは `haiku serve` の自前ホスト版を使う）。

データはここで注入するので、data/*.json を更新したら再生成すれば同期する。
"""

from __future__ import annotations

import json
from pathlib import Path

from . import db

from .reading import BUILTIN_READINGS

TEMPLATE = Path(__file__).parent / "web" / "static" / "artifact_template.html"
PLACEHOLDER = "/*__DATA__*/"


def build_payload(data_dir: Path | None = None) -> dict:
    """テンプレートに埋め込む JSON を組み立てる。キーは転送量を抑えるため 1 文字。"""
    data = db.load_json(data_dir)

    # 読み辞書は Python 側と同一のものを使う。ここで独自に拡張すると
    # CLI と配布 HTML で音数がずれる。
    #
    # 傍題を足したくなるが、足してはいけない。傍題の読みはデータに無く、
    # 見出し語の読みで代用すると誤る（「小春日和」→「こはる」など）。
    readings = {**BUILTIN_READINGS, **data.reading_dictionary()}

    return {
        "kigo": [
            {
                "w": k.word,
                "k": k.kana,
                "s": k.season,
                "c": k.category,
                "a": list(k.aliases),
                "n": k.note,
            }
            for k in data.kigo
        ],
        "famous": [{"t": f.text, "k": f.kana, "a": f.author} for f in data.famous],
        "readings": readings,
    }


def build(output: Path, data_dir: Path | None = None) -> Path:
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise RuntimeError(f"テンプレートに {PLACEHOLDER} がありません: {TEMPLATE}")

    payload = json.dumps(build_payload(data_dir), ensure_ascii=False, separators=(",", ":"))
    html = template.replace(PLACEHOLDER, payload)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output
