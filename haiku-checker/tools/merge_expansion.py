"""季節ごとに分割生成した季語データを本体へ統合する。

サブエージェントの出力を鵜呑みにせず、統合の前に機械で弾けるものは弾く。
既存語との衝突、季節の取り違え、読みの不正、誤検出を招きやすい語を検出する。

    python tools/merge_expansion.py <出力ディレクトリ> [--apply]

--apply を付けるまで data/saijiki.json は書き換えない。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from check_saijiki import check_structure  # noqa: E402
from format_saijiki import format_file  # noqa: E402

SEASON_OF_FILE = {
    "spring.json": "春",
    "summer.json": "夏",
    "autumn.json": "秋",
    "winter.json": "冬",
    "newyear.json": "新年",
}


def load_batches(src: Path) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    problems: list[str] = []
    for name, season in SEASON_OF_FILE.items():
        path = src / name
        if not path.exists():
            problems.append(f"{name}: 見つからない（未完了）")
            continue
        batch = json.loads(path.read_text("utf-8"))
        wrong = [e.get("word") for e in batch if e.get("season") != season]
        if wrong:
            problems.append(f"{name}: 季節が '{season}' でないエントリ {len(wrong)} 件 → {wrong[:5]}")
        entries.extend(batch)
        print(f"  {name}: {len(batch)} 件 ({season})")
    return entries, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path, help="季節別 JSON を置いたディレクトリ")
    ap.add_argument("--apply", action="store_true", help="data/saijiki.json を実際に書き換える")
    args = ap.parse_args()

    print("読み込み:")
    new_entries, problems = load_batches(args.src)

    target = ROOT / "data" / "saijiki.json"
    data = json.loads(target.read_text("utf-8"))
    base = data["entries"]
    print(f"\n既存 {len(base)} 件 + 新規 {len(new_entries)} 件 = {len(base) + len(new_entries)} 件")

    merged = base + new_entries
    errors = check_structure(merged)

    print()
    if problems:
        print(f"取り込み前の問題（{len(problems)} 件）")
        for p in problems:
            print(f"  - {p}")
    if errors:
        print(f"構造検証: 不合格（{len(errors)} 件）")
        for e in errors[:40]:
            print(f"  - {e}")
        if len(errors) > 40:
            print(f"  … 他 {len(errors) - 40} 件")
        print("\n修正するまで統合しない。")
        return 1

    print("構造検証: 合格")
    if problems:
        print("※ 未完了のバッチがあるため、この統合は部分的")

    if not args.apply:
        print("\n（--apply を付けると data/saijiki.json に書き込む）")
        return 0

    data["entries"] = merged
    data["note"] = (
        f"季語 {len(merged)} 件。季節は 春/夏/秋/冬/新年 の5区分、"
        "分類は 時候/天文/地理/生活/行事/動物/植物 の7区分。"
        "季語そのものは伝統的な語彙であり、特定の出版歳時記の項目立てを写したものではない。例句は含まない。"
    )
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    count = format_file(target)
    print(f"\n統合した: {target}（{count} 件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
