"""歳時記データの構造検証と、検出精度の計測。

季語を増やすと誤検出も増える。増やしたあとにこれを走らせ、構造の妥当性と
「有名句 1 句あたりの検出季語数」が悪化していないかを確認する。

使い方:
    python tools/check_saijiki.py                 # 検証＋計測
    python tools/check_saijiki.py --baseline out.json   # 現状を基準値として保存
    python tools/check_saijiki.py --compare out.json    # 基準値と比較して合否判定
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from haiku_checker import db, kana as kana_util  # noqa: E402
from haiku_checker.reading import get_reader, read_with_override  # noqa: E402
from haiku_checker.saijiki import MIN_KANA_MATCH_LEN, SaijikiMatcher  # noqa: E402

SEASONS = {"春", "夏", "秋", "冬", "新年"}
CATEGORIES = {"時候", "天文", "地理", "生活", "行事", "動物", "植物"}

# 季語として登録してはいけない、季節を持たない日常語。
# これらを入れると、ほぼ全ての句が季語ありと誤判定される。
FORBIDDEN_WORDS = {
    "空", "道", "人", "手", "目", "口", "耳", "足", "声", "音", "色", "光", "影",
    "家", "町", "村", "駅", "窓", "扉", "部屋", "机", "本", "紙", "水", "火",
    "土", "石", "木", "山", "川", "海", "森", "林", "野", "橋", "心", "命",
    "夢", "涙", "今", "昔", "母", "父", "子", "私", "僕", "君", "犬", "猫",
}


def check_structure(entries: list[dict]) -> list[str]:
    """構造上の誤りを列挙する。空リストなら合格。"""
    errors: list[str] = []
    seen_words: dict[str, dict] = {}
    surface_seasons: dict[str, set[str]] = collections.defaultdict(set)

    for i, e in enumerate(entries):
        where = f"[{i}] {e.get('word', '?')}"

        for field in ("word", "kana", "season", "category"):
            if not e.get(field):
                errors.append(f"{where}: {field} が空")

        if e.get("season") not in SEASONS:
            errors.append(f"{where}: 季節 '{e.get('season')}' が不正")
        if e.get("category") not in CATEGORIES:
            errors.append(f"{where}: 分類 '{e.get('category')}' が不正")

        kana = e.get("kana", "")
        if kana and kana_util.kana_only(kana) != kana_util.to_hiragana(kana):
            errors.append(f"{where}: kana '{kana}' にかな以外が含まれる")
        if kana and kana_util.contains_kanji(kana):
            errors.append(f"{where}: kana '{kana}' に漢字が含まれる")

        word = e.get("word", "")
        if word in FORBIDDEN_WORDS:
            errors.append(f"{where}: 季節を持たない日常語は登録できない")
        if word in seen_words:
            prev = seen_words[word]
            errors.append(f"{where}: 見出し語が重複（既出: {prev['season']}・{prev['category']}）")
        else:
            seen_words[word] = e

        aliases = e.get("aliases", [])
        if not isinstance(aliases, list):
            errors.append(f"{where}: aliases が配列でない")
            aliases = []
        if word in aliases:
            errors.append(f"{where}: 傍題に見出し語自身が入っている")
        if len(set(aliases)) != len(aliases):
            errors.append(f"{where}: 傍題が重複している")

        for surface in [word, *aliases]:
            if surface in FORBIDDEN_WORDS:
                errors.append(f"{where}: 傍題 '{surface}' は季節を持たない日常語")
            surface_seasons[surface].add(e.get("season", "?"))

    for surface, seasons in surface_seasons.items():
        if len(seasons) > 1:
            errors.append(f"表記 '{surface}' が複数の季節に登録されている: {'・'.join(sorted(seasons))}")

    return errors


def measure_precision(data) -> dict:
    """有名句コーパスに対する検出季語数の分布を測る。

    俳句は原則として季語ひとつ。1 句あたりの検出数が増えていれば誤検出が
    増えたということ。
    """
    matcher = SaijikiMatcher(data)
    reader = get_reader(extra_dictionary=data.reading_dictionary())

    counts = collections.Counter()
    per_haiku: dict[str, list[str]] = {}
    for f in data.famous:
        reading = read_with_override(f.text, f.kana or None, reader)
        hits = matcher.find(f.text, reading.kana, tokens=reading.tokens)
        words = [h.kigo.word for h in hits]
        counts[len(words)] += 1
        per_haiku[f.text] = words

    total = sum(counts.values())
    multi = sum(v for k, v in counts.items() if k >= 3)
    return {
        "corpus_size": total,
        "distribution": {str(k): counts[k] for k in sorted(counts)},
        "avg_kigo_per_haiku": round(sum(k * v for k, v in counts.items()) / max(total, 1), 3),
        "haiku_with_3plus_kigo": multi,
        "no_kigo": counts[0],
        "per_haiku": per_haiku,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=Path, help="現状を基準値として保存する")
    ap.add_argument("--compare", type=Path, help="基準値と比較して合否を判定する")
    args = ap.parse_args()

    raw = json.loads((Path(__file__).resolve().parents[1] / "data" / "saijiki.json").read_text("utf-8"))
    entries = raw["entries"]
    data = db.load_json()

    print(f"季語 {len(entries)} 件")
    by = collections.Counter((e["season"], e["category"]) for e in entries)
    cats = ["時候", "天文", "地理", "生活", "行事", "動物", "植物"]
    print(f"{'':6s}" + "".join(f"{c:>6s}" for c in cats) + "     計")
    for s in ["春", "夏", "秋", "冬", "新年"]:
        row = [by[(s, c)] for c in cats]
        print(f"{s:6s}" + "".join(f"{v:6d}" for v in row) + f"{sum(row):7d}")

    errors = check_structure(entries)
    print()
    if errors:
        print(f"構造検証: 不合格（{len(errors)} 件）")
        for e in errors[:40]:
            print(f"  - {e}")
        if len(errors) > 40:
            print(f"  … 他 {len(errors) - 40} 件")
    else:
        print("構造検証: 合格")

    metrics = measure_precision(data)
    print()
    print(f"精度計測（有名句 {metrics['corpus_size']} 句）")
    print(f"  1 句あたりの検出季語数（平均）: {metrics['avg_kigo_per_haiku']}")
    print(f"  検出数の分布: {metrics['distribution']}")
    print(f"  季語 3 語以上を検出した句: {metrics['haiku_with_3plus_kigo']} 句")
    print(f"  季語ゼロの句: {metrics['no_kigo']} 句")

    if args.baseline:
        args.baseline.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), "utf-8")
        print(f"\n基準値を保存: {args.baseline}")

    failed = bool(errors)
    if args.compare and args.compare.exists():
        base = json.loads(args.compare.read_text("utf-8"))
        print("\n基準値との比較")
        d_avg = metrics["avg_kigo_per_haiku"] - base["avg_kigo_per_haiku"]
        d_multi = metrics["haiku_with_3plus_kigo"] - base["haiku_with_3plus_kigo"]
        d_zero = metrics["no_kigo"] - base["no_kigo"]
        print(f"  平均検出数: {base['avg_kigo_per_haiku']} → {metrics['avg_kigo_per_haiku']} ({d_avg:+.3f})")
        print(f"  3 語以上の句: {base['haiku_with_3plus_kigo']} → {metrics['haiku_with_3plus_kigo']} ({d_multi:+d})")
        print(f"  季語ゼロの句: {base['no_kigo']} → {metrics['no_kigo']} ({d_zero:+d})  ※減るのは改善")

        # 季語が増えれば検出は増えるが、増えすぎは誤検出。1 句 3 語以上が
        # 急増していないかで見る。
        if d_multi > 8:
            print("  → 不合格: 3 語以上を検出する句が増えすぎている（誤検出の疑い）")
            failed = True
        else:
            print("  → 合格")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
