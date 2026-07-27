"""歳時記 JSON を 1 エントリ 1 行に整形する。

`json.dumps(indent=2)` で書き戻すと 1 エントリが 8 行に展開され、数語の追加でも
数千行の差分になってレビューできない。エントリを 1 行に畳んで差分を追えるようにする。

    python tools/format_saijiki.py data/saijiki.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# エントリ内のキーの並び順。ここで固定しないと差分が安定しない。
KEY_ORDER = ["word", "kana", "season", "category", "aliases", "note"]
SEASON_ORDER = {"春": 0, "夏": 1, "秋": 2, "冬": 3, "新年": 4}
CATEGORY_ORDER = {
    "時候": 0, "天文": 1, "地理": 2, "生活": 3, "行事": 4, "動物": 5, "植物": 6,
}


def format_file(path: Path, sort: bool = True) -> int:
    data = json.loads(path.read_text("utf-8"))
    entries = data["entries"]

    if sort:
        entries.sort(
            key=lambda e: (
                SEASON_ORDER.get(e.get("season", ""), 99),
                CATEGORY_ORDER.get(e.get("category", ""), 99),
                e.get("kana", ""),
            )
        )

    lines: list[str] = []
    for e in entries:
        ordered = {k: e[k] for k in KEY_ORDER if k in e}
        ordered.update({k: v for k, v in e.items() if k not in KEY_ORDER})
        lines.append("    " + json.dumps(ordered, ensure_ascii=False))

    head = {k: v for k, v in data.items() if k != "entries"}
    head_json = json.dumps(head, ensure_ascii=False, indent=2)
    body = ",\n".join(lines)
    text = head_json[:-2].rstrip() + ',\n  "entries": [\n' + body + "\n  ]\n}\n"

    json.loads(text)  # 書き出す前に自分で読み直して壊れていないことを確認する
    path.write_text(text, "utf-8")
    return len(entries)


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "data/saijiki.json")
    count = format_file(target)
    print(f"{target}: {count} 件を整形（季節→分類→読み順）")
