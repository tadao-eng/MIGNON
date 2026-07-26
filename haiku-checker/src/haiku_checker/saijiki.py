"""① 歳時記照合モジュール。

入力句に対して次を判定する。

  - 正しい季語が含まれているか（季語の検出と季節の特定）
  - 季重なり（複数の季語）が起きていないか
  - 季節外れの語が混ざっていないか（投句時期・指定季節との照合）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import kana as kana_util
from .db import Kigo, Saijiki

# かな表記でのみ一致させる場合の最小長。「か」（蚊）のような 1〜2 音の語を
# かな本文から拾うと誤検出だらけになるため、かな一致は 3 音以上に限る。
MIN_KANA_MATCH_LEN = 3

# 陰暦ベースの季節区分に近い、実用的な月→季節の対応。
MONTH_SEASON = {
    1: "新年", 2: "春", 3: "春", 4: "春", 5: "夏", 6: "夏",
    7: "夏", 8: "秋", 9: "秋", 10: "秋", 11: "冬", 12: "冬",
}


@dataclass(frozen=True)
class KigoHit:
    kigo: Kigo
    matched_surface: str
    start: int
    end: int
    matched_by: str  # "surface" | "kana"

    @property
    def season(self) -> str:
        return self.kigo.season


@dataclass
class SaijikiReport:
    hits: list[KigoHit] = field(default_factory=list)
    primary_season: str | None = None
    seasons: list[str] = field(default_factory=list)
    kigasanari: bool = False           # 同季の季重なり
    kichigai: bool = False             # 異なる季節の季語が同居（季違い）
    muki: bool = False                 # 無季（季語なし）
    out_of_season: list[KigoHit] = field(default_factory=list)
    target_season: str | None = None
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kigo": [
                {
                    "word": h.kigo.word,
                    "matched": h.matched_surface,
                    "kana": h.kigo.kana,
                    "season": h.kigo.season,
                    "category": h.kigo.category,
                    "note": h.kigo.note,
                    "matched_by": h.matched_by,
                }
                for h in self.hits
            ],
            "primary_season": self.primary_season,
            "seasons": self.seasons,
            "muki": self.muki,
            "kigasanari": self.kigasanari,
            "kichigai": self.kichigai,
            "target_season": self.target_season,
            "out_of_season": [h.kigo.word for h in self.out_of_season],
            "warnings": self.warnings,
            "notes": self.notes,
        }


class SaijikiMatcher:
    def __init__(self, saijiki: Saijiki) -> None:
        self.saijiki = saijiki
        self._surface_index: dict[str, list[Kigo]] = {}
        self._kana_index: dict[str, list[Kigo]] = {}
        for k in saijiki.kigo:
            for surface in k.surfaces:
                self._surface_index.setdefault(kana_util.normalize(surface), []).append(k)
            for kana in {k.kana, *(kana_util.kana_only(a) for a in k.surfaces)}:
                kana = kana_util.to_hiragana(kana)
                if kana and kana_util.count_mora(kana) >= MIN_KANA_MATCH_LEN:
                    self._kana_index.setdefault(kana, []).append(k)
        self._max_surface = max((len(s) for s in self._surface_index), default=1)
        self._max_kana = max((len(s) for s in self._kana_index), default=1)

    # ------------------------------------------------------------------ 検出

    @staticmethod
    def kana_runs(tokens) -> list[str]:
        """本文がかなで書かれている連続部分だけを取り出す。

        読み一致は「作者がかなで書いた季語」を拾うための経路なので、漢字の読みまで
        含めた一続きの読み文字列を走査すると語をまたいだ誤検出が起きる。
        例:「この道や…」の読み「このみち」から「木の実（このみ）」を拾ってしまう。
        漢字のトークンで区切ることでこれを防ぐ。
        """
        runs: list[str] = []
        current = ""
        for tok in tokens:
            surface = tok.surface
            if surface and not kana_util.contains_kanji(surface) and tok.kana:
                current += tok.kana
            else:
                if current:
                    runs.append(current)
                current = ""
        if current:
            runs.append(current)
        return runs

    def find(self, text: str, reading_kana: str = "", tokens=None) -> list[KigoHit]:
        """本文（漢字仮名交じり）と読みの両方から季語を最長一致で拾う。

        `tokens` を渡すと、読み一致の走査をかな表記の部分に限定して精度を上げる。
        """
        hits = self._scan(kana_util.normalize(text), self._surface_index, self._max_surface, "surface")
        found_ids = {h.kigo.id for h in hits}

        targets = self.kana_runs(tokens) if tokens else []
        if not targets and reading_kana:
            # 読みをユーザーが与えた場合はトークンが 1 個で語境界が取れない。
            # その場合だけ読み全体を走査対象にする（誤検出より取り逃しを避ける）。
            targets = [kana_util.to_hiragana(reading_kana)]

        for target in targets:
            for hit in self._scan(target, self._kana_index, self._max_kana, "kana"):
                if hit.kigo.id not in found_ids:
                    hits.append(hit)
                    found_ids.add(hit.kigo.id)

        hits.sort(key=lambda h: (h.matched_by != "surface", h.start))
        return hits

    def _scan(
        self,
        text: str,
        index: dict[str, list[Kigo]],
        max_len: int,
        matched_by: str,
    ) -> list[KigoHit]:
        hits: list[KigoHit] = []
        seen_ids: set[int] = set()
        i = 0
        while i < len(text):
            for length in range(min(max_len, len(text) - i), 0, -1):
                chunk = text[i : i + length]
                candidates = index.get(chunk)
                if not candidates:
                    continue
                for kigo in candidates:
                    if kigo.id in seen_ids:
                        continue
                    seen_ids.add(kigo.id)
                    hits.append(KigoHit(kigo, chunk, i, i + length, matched_by))
                i += length
                break
            else:
                i += 1
        return hits

    # ------------------------------------------------------------------ 判定

    def analyze(
        self,
        text: str,
        reading_kana: str = "",
        target_season: str | None = None,
        submission_date: date | None = None,
        tokens=None,
    ) -> SaijikiReport:
        hits = self.find(text, reading_kana, tokens=tokens)
        report = SaijikiReport(hits=hits)

        if target_season is None and submission_date is not None:
            target_season = MONTH_SEASON.get(submission_date.month)
        report.target_season = target_season

        if not hits:
            report.muki = True
            report.warnings.append(
                "季語が検出できませんでした。有季定型の大会では失格扱いになる場合があります"
                "（無季を許容する大会か、収録漏れの季語かをご確認ください）。"
            )
            return report

        seasons: list[str] = []
        for h in hits:
            if h.season not in seasons:
                seasons.append(h.season)
        report.seasons = seasons

        # 主たる季語は「本文表記で一致した最初の季語」を採用する。
        surface_hits = [h for h in hits if h.matched_by == "surface"]
        report.primary_season = (surface_hits or hits)[0].season

        if len(hits) > 1:
            if len(seasons) == 1:
                report.kigasanari = True
                words = "・".join(h.kigo.word for h in hits)
                report.warnings.append(
                    f"季重なりです（{seasons[0]}の季語が {len(hits)} 語：{words}）。"
                    "意図した効果でなければ、主となる一語を残して他は言い換えを検討してください。"
                )
            else:
                report.kichigai = True
                detail = "、".join(f"{h.kigo.word}（{h.season}）" for h in hits)
                report.warnings.append(
                    f"異なる季節の季語が同居しています（季違い）：{detail}。"
                    "句の季節が定まらず、選から漏れる大きな要因になります。"
                )

        if target_season:
            out = [h for h in hits if h.season != target_season]
            report.out_of_season = out
            if out:
                detail = "、".join(f"{h.kigo.word}（{h.season}）" for h in out)
                report.warnings.append(
                    f"投句時期の季節「{target_season}」と合わない季語があります：{detail}。"
                    "当季雑詠の大会では要注意です。"
                )

        for h in hits:
            if h.kigo.note:
                report.notes.append(f"{h.kigo.word}：{h.kigo.note}")
            if h.matched_by == "kana":
                report.notes.append(
                    f"{h.kigo.word}（{h.kigo.kana}）は読みからの推定一致です。誤検出の可能性があります。"
                )
        return report


def season_for_date(d: date) -> str:
    return MONTH_SEASON.get(d.month, "")
