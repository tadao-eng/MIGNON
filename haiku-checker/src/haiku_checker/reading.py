"""俳句本文の読み（かな）推定。

音数を数えるには漢字仮名交じり文をかなに開く必要がある。janome が入っていれば
形態素解析で読みを取り、無ければ歳時記の見出し語＋常用語の内蔵辞書で最長一致を
試みる。どちらでも読めない部分は `unknown` に載せ、CLI 側で `--yomi` の指定を促す。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from . import kana as kana_util

# 内蔵フォールバック辞書。俳句に頻出し、かつ歳時記に載らない一般語を補う。
BUILTIN_READINGS: dict[str, str] = {
    "私": "わたし", "僕": "ぼく", "君": "きみ", "母": "はは", "父": "ちち",
    "子": "こ", "人": "ひと", "手": "て", "足": "あし", "目": "め", "耳": "みみ",
    "口": "くち", "声": "こえ", "音": "おと", "色": "いろ", "光": "ひかり",
    "影": "かげ", "空": "そら", "海": "うみ", "山": "やま", "川": "かわ",
    "河": "かわ", "田": "た", "森": "もり", "林": "はやし", "野": "の",
    "町": "まち", "村": "むら", "道": "みち", "橋": "はし", "駅": "えき",
    "家": "いえ", "窓": "まど", "戸": "と", "門": "もん", "庭": "にわ",
    "部屋": "へや", "机": "つくえ", "椅子": "いす", "本": "ほん", "紙": "かみ",
    "水": "みず", "火": "ひ", "風": "かぜ", "土": "つち", "石": "いし",
    "木": "き", "葉": "は", "花": "はな", "実": "み", "根": "ね", "草": "くさ",
    "鳥": "とり", "犬": "いぬ", "猫": "ねこ", "馬": "うま", "牛": "うし",
    "魚": "さかな", "虫": "むし", "朝": "あさ", "昼": "ひる", "夜": "よる",
    "夕": "ゆう", "今日": "きょう", "明日": "あす", "昨日": "きのう",
    "今": "いま", "先": "さき", "上": "うえ", "下": "した", "中": "なか",
    "外": "そと", "内": "うち", "前": "まえ", "後": "あと", "右": "みぎ",
    "左": "ひだり", "北": "きた", "南": "みなみ", "東": "ひがし", "西": "にし",
    "白": "しろ", "黒": "くろ", "赤": "あか", "青": "あお", "黄": "き",
    "一": "いち", "二": "に", "三": "さん", "四": "し", "五": "ご",
    "六": "ろく", "七": "しち", "八": "はち", "九": "きゅう", "十": "じゅう",
    "百": "ひゃく", "千": "せん", "万": "まん", "年": "とし", "月": "つき",
    "日": "ひ", "時": "とき", "間": "あいだ", "所": "ところ", "事": "こと",
    "物": "もの", "心": "こころ", "命": "いのち", "夢": "ゆめ", "涙": "なみだ",
    "笑": "わら", "泣": "な", "見": "み", "聞": "き", "行": "い", "来": "き",
    "居": "い", "立": "た", "座": "すわ", "歩": "ある", "走": "はし",
    "飛": "と", "落": "お", "散": "ち", "咲": "さ", "降": "ふ", "吹": "ふ",
    "流": "なが", "光る": "ひかる", "残": "のこ", "消": "き",
}


@dataclass
class ReadingToken:
    surface: str
    kana: str
    part_of_speech: str = ""

    @property
    def mora(self) -> int:
        return kana_util.count_mora(self.kana)


@dataclass
class ReadingResult:
    kana: str
    tokens: list[ReadingToken] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    engine: str = "fallback"

    @property
    def reliable(self) -> bool:
        return not self.unknown


class Reader:
    """漢字仮名交じりの俳句をかなに開く基底クラス。"""

    name = "base"

    def read(self, text: str) -> ReadingResult:  # pragma: no cover - interface
        raise NotImplementedError


class JanomeReader(Reader):
    name = "janome"

    def __init__(self) -> None:
        from janome.tokenizer import Tokenizer  # 遅延 import（任意依存のため）

        self._tokenizer = Tokenizer()

    def read(self, text: str) -> ReadingResult:
        tokens: list[ReadingToken] = []
        unknown: list[str] = []
        for tok in self._tokenizer.tokenize(text):
            surface = tok.surface
            reading = getattr(tok, "reading", "*")
            if reading and reading != "*":
                kana = kana_util.to_hiragana(reading)
            elif not kana_util.contains_kanji(surface):
                kana = kana_util.to_hiragana(surface)
            else:
                kana = ""
                unknown.append(surface)
            tokens.append(ReadingToken(surface, kana, tok.part_of_speech.split(",")[0]))
        return ReadingResult(
            kana="".join(t.kana for t in tokens),
            tokens=tokens,
            unknown=unknown,
            engine=self.name,
        )


class DictionaryReader(Reader):
    """最長一致による簡易読み付与。janome が無い環境でのフォールバック。"""

    name = "dictionary"

    def __init__(self, extra: dict[str, str] | None = None) -> None:
        self._dict: dict[str, str] = dict(BUILTIN_READINGS)
        if extra:
            self._dict.update(extra)
        self._max_len = max((len(k) for k in self._dict), default=1)

    def read(self, text: str) -> ReadingResult:
        tokens: list[ReadingToken] = []
        unknown: list[str] = []
        i = 0
        while i < len(text):
            ch = text[i]
            if not kana_util.contains_kanji(ch):
                # かな・記号はそのまま（記号は count_mora が無視する）
                tokens.append(ReadingToken(ch, kana_util.to_hiragana(ch) if kana_util.is_kana(ch) else ""))
                i += 1
                continue
            matched = False
            for length in range(min(self._max_len, len(text) - i), 0, -1):
                chunk = text[i : i + length]
                if chunk in self._dict:
                    tokens.append(ReadingToken(chunk, self._dict[chunk]))
                    i += length
                    matched = True
                    break
            if not matched:
                unknown.append(ch)
                tokens.append(ReadingToken(ch, ""))
                i += 1
        return ReadingResult(
            kana="".join(t.kana for t in tokens),
            tokens=tokens,
            unknown=unknown,
            engine=self.name,
        )


@lru_cache(maxsize=1)
def _janome_available() -> bool:
    try:
        import janome  # noqa: F401
    except ImportError:
        return False
    return True


def get_reader(extra_dictionary: dict[str, str] | None = None, prefer: str | None = None) -> Reader:
    """利用可能な最良のリーダーを返す。

    prefer="dictionary" を渡すと janome があっても内蔵辞書を使う（テスト用）。
    """
    if prefer != "dictionary" and _janome_available():
        try:
            return JanomeReader()
        except Exception:  # 辞書ロード失敗時はフォールバック
            pass
    return DictionaryReader(extra_dictionary)


def read_with_override(text: str, yomi: str | None, reader: Reader) -> ReadingResult:
    """`--yomi` が与えられていればそれを優先し、無ければ推定する。"""
    if yomi:
        clean = kana_util.kana_only(yomi)
        return ReadingResult(kana=clean, tokens=[ReadingToken(text, clean)], engine="user")
    return reader.read(text)
