"""かなの正規化と俳句のモーラ（音数）計算。

俳句の音数は「かな一文字＝一音」を基本に、以下の例外を持つ。

  - 拗音（ゃゅょ など小書き文字）は直前の音に含めるため数えない
  - 促音「っ」、撥音「ん」、長音「ー」はそれぞれ一音として数える
"""

from __future__ import annotations

import re
import unicodedata

# 直前の音に吸収され、独立した一音を作らない小書き文字。
NON_MORAIC = set("ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ")

# 小書きだが一音を担う文字（「三ヶ日」の「ヶ」など）。
MORAIC_SMALL = set("ゕゖヵヶ")

_HIRAGANA_RANGE = (0x3041, 0x3096)
_KATAKANA_RANGE = (0x30A1, 0x30FA)

_KANA_RE = re.compile(r"[ぁ-ゖァ-ヺーー]")

# 分かち書きの区切りとして扱う文字（半角/全角スペース、スラッシュ、縦棒）。
SEGMENT_SEPARATORS = " 　/／|｜\t"


def to_hiragana(text: str) -> str:
    """カタカナをひらがなに変換する。長音符「ー」はそのまま残す。"""
    out = []
    for ch in text:
        code = ord(ch)
        if _KATAKANA_RANGE[0] <= code <= _KATAKANA_RANGE[1]:
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def normalize(text: str) -> str:
    """入力表記のゆれを吸収する（NFKC 正規化＋前後の空白除去）。"""
    return unicodedata.normalize("NFKC", text).strip()


def kana_only(text: str) -> str:
    """かな以外（漢字・記号・空白）を取り除いたひらがな列を返す。"""
    return "".join(_KANA_RE.findall(to_hiragana(text)))


def kana_runs(text: str) -> list[str]:
    """本文の中で、かなが続いている部分だけを取り出す。

    読み一致で季語を拾うときの走査範囲を決めるのに使う。漢字の読みまで繋いだ
    一続きの読み文字列を走査すると、語をまたいだ偶然の並びを拾ってしまう。
    例:「連山影を」の読み「れんざんかげを」から「残花（ざんか）」を拾う。
    漢字を区切りとして扱うことでこれを防ぐ。
    """
    runs: list[str] = []
    current = ""
    for ch in to_hiragana(normalize(text)):
        if is_kana(ch):
            current += ch
        else:
            if current:
                runs.append(current)
            current = ""
    if current:
        runs.append(current)
    return runs


def is_kana(ch: str) -> bool:
    code = ord(ch)
    return (
        _HIRAGANA_RANGE[0] <= code <= _HIRAGANA_RANGE[1]
        or _KATAKANA_RANGE[0] <= code <= _KATAKANA_RANGE[1]
        or ch in "ーー"
    )


def contains_kanji(text: str) -> bool:
    return any(0x4E00 <= ord(ch) <= 0x9FFF or 0x3400 <= ord(ch) <= 0x4DBF for ch in text)


def count_mora(kana: str) -> int:
    """ひらがな／カタカナ列の音数を数える。かな以外の文字は無視する。"""
    total = 0
    for ch in to_hiragana(kana):
        if ch in NON_MORAIC:
            continue
        if ch in MORAIC_SMALL:
            total += 1
            continue
        if is_kana(ch):
            total += 1
    return total


def mora_list(kana: str) -> list[str]:
    """かな列をモーラ単位に区切ったリストを返す（「きょ」→ ["きょ"]）。"""
    text = to_hiragana(kana)
    moras: list[str] = []
    for ch in text:
        if ch in NON_MORAIC and moras:
            moras[-1] += ch
            continue
        if ch in NON_MORAIC:
            # 行頭の小書き文字は単独で扱うしかない
            moras.append(ch)
            continue
        if is_kana(ch) or ch in MORAIC_SMALL:
            moras.append(ch)
    return moras


def has_explicit_separator(text: str) -> bool:
    return any(sep in text for sep in SEGMENT_SEPARATORS)


def split_on_separators(text: str) -> list[str]:
    parts = re.split(f"[{re.escape(SEGMENT_SEPARATORS)}]+", text)
    return [p for p in parts if p]
