"""五・七・五の分割と定型判定。

区切りが明示されていればそれに従い、無ければ形態素（または文字）境界のうち
5/7/5 からのズレが最小になる位置で分割する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import kana as kana_util
from .reading import ReadingResult, ReadingToken

IDEAL = (5, 7, 5)
SEGMENT_NAMES = ("上五", "中七", "下五")

# 切字（句の切れを作る語）。位置の妥当性チェックに使う。
KIREJI = ("や", "かな", "けり", "なり", "ぞ", "か", "よ", "し", "つ", "ぬ", "らむ", "けむ")


@dataclass
class Segment:
    name: str
    text: str
    kana: str
    mora: int
    ideal: int

    @property
    def delta(self) -> int:
        return self.mora - self.ideal

    @property
    def label(self) -> str:
        if self.delta == 0:
            return "定型"
        if self.delta > 0:
            return f"字余り+{self.delta}"
        return f"字足らず{self.delta}"


@dataclass
class StructureReport:
    segments: list[Segment] = field(default_factory=list)
    total_mora: int = 0
    is_teikei: bool = False
    split_source: str = "auto"  # "explicit" | "token" | "char" | "user"
    confident: bool = True
    kireji: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def pattern(self) -> str:
        return "・".join(str(s.mora) for s in self.segments)

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "total_mora": self.total_mora,
            "is_teikei": self.is_teikei,
            "split_source": self.split_source,
            "confident": self.confident,
            "kireji": self.kireji,
            "segments": [
                {
                    "name": s.name,
                    "text": s.text,
                    "kana": s.kana,
                    "mora": s.mora,
                    "ideal": s.ideal,
                    "delta": s.delta,
                    "label": s.label,
                }
                for s in self.segments
            ],
            "warnings": self.warnings,
        }


def _segments_from_tokens(tokens: list[ReadingToken]) -> list[Segment] | None:
    """トークン境界で 5/7/5 に最も近い分割を総当たりで探す。"""
    usable = [t for t in tokens if t.kana or t.surface.strip()]
    if len(usable) < 3:
        return None

    moras = [kana_util.count_mora(t.kana) for t in usable]
    n = len(usable)
    best: tuple[int, int, int] | None = None
    best_cost = None
    for i in range(1, n - 1):
        for j in range(i + 1, n):
            a = sum(moras[:i])
            b = sum(moras[i:j])
            c = sum(moras[j:])
            if a == 0 or b == 0 or c == 0:
                continue
            cost = abs(a - 5) * 2 + abs(b - 7) + abs(c - 5) * 2
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best = (i, j, cost)
    if best is None:
        return None

    i, j, _ = best
    groups = [usable[:i], usable[i:j], usable[j:]]
    return [
        Segment(
            name=SEGMENT_NAMES[idx],
            text="".join(t.surface for t in group),
            kana="".join(t.kana for t in group),
            mora=sum(kana_util.count_mora(t.kana) for t in group),
            ideal=IDEAL[idx],
        )
        for idx, group in enumerate(groups)
    ]


def _segments_from_kana(kana: str) -> list[Segment]:
    """トークン情報が無い場合に、モーラ数だけで 5/12 の位置を切る。"""
    moras = kana_util.mora_list(kana)
    cuts = (5, 12)
    groups = [moras[: cuts[0]], moras[cuts[0] : cuts[1]], moras[cuts[1] :]]
    segments = []
    for idx, group in enumerate(groups):
        joined = "".join(group)
        segments.append(
            Segment(
                name=SEGMENT_NAMES[idx],
                text=joined,
                kana=joined,
                mora=len(group),
                ideal=IDEAL[idx],
            )
        )
    return segments


def detect_kireji(segments: list[Segment]) -> list[str]:
    found = []
    for seg in segments:
        for k in ("かな", "けり", "なり", "らむ", "けむ"):
            if seg.kana.endswith(k):
                found.append(f"{seg.name}末「{k}」")
                break
        else:
            if seg.kana.endswith("や") and seg.name != "下五":
                found.append(f"{seg.name}末「や」")
    return found


def analyze(
    text: str,
    reading: ReadingResult,
    reader=None,
    user_yomi: str | None = None,
) -> StructureReport:
    """句を上五／中七／下五に分けて定型を判定する。

    `user_yomi` が与えられた場合、その読みを推定より優先する。上五／中七／下五を
    スペースで区切った読みを渡すと各節の音数まで正確に判定できる。
    """
    report = StructureReport()
    yomi_parts = kana_util.split_on_separators(user_yomi) if user_yomi else []

    if kana_util.has_explicit_separator(text):
        parts = kana_util.split_on_separators(text)
        if len(parts) == 3:
            if len(yomi_parts) == 3:
                # ユーザーが節ごとの読みを与えた場合はそれを最優先する。
                kanas = [kana_util.kana_only(p) for p in yomi_parts]
                source = "user"
            elif user_yomi:
                # 読みが一続きで与えられている。節ごとの対応は取れないため、
                # 全体の音数を正としてモーラ単位で機械的に割る。
                kanas = None
                source = "user-total"
            else:
                kanas = [
                    reader.read(p).kana
                    if (kana_util.contains_kanji(p) and reader is not None)
                    else kana_util.kana_only(p)
                    for p in parts
                ]
                source = "explicit"

            if kanas is None:
                report.segments = _segments_from_kana(kana_util.kana_only(user_yomi))
                report.split_source = "user-total"
                report.warnings.append(
                    "読みが一続きで指定されたため、各節の音数はモーラ数だけで機械的に割りました。"
                    "節ごとに正確に見るには `--yomi` も上五／中七／下五をスペースで区切ってください。"
                )
            else:
                report.segments = [
                    Segment(
                        name=SEGMENT_NAMES[idx],
                        text=parts[idx],
                        kana=kanas[idx],
                        mora=kana_util.count_mora(kanas[idx]),
                        ideal=IDEAL[idx],
                    )
                    for idx in range(3)
                ]
                report.split_source = source
        else:
            report.warnings.append(
                f"区切り文字で {len(parts)} 分割されました。上五／中七／下五の 3 つに区切ってください。"
            )

    if not report.segments:
        segments = _segments_from_tokens(reading.tokens) if reading.tokens else None
        if segments:
            report.segments = segments
            report.split_source = "token"
        else:
            report.segments = _segments_from_kana(reading.kana)
            report.split_source = "char"
            report.confident = False
            report.warnings.append(
                "語の境界が取れなかったため音数だけで機械的に区切りました。"
                "正確に見るには半角スペースで上五／中七／下五を区切って入力してください。"
            )

    report.total_mora = sum(s.mora for s in report.segments)
    report.is_teikei = all(s.delta == 0 for s in report.segments)
    report.kireji = detect_kireji(report.segments)

    if not reading.reliable:
        report.confident = False
        unknown = "・".join(dict.fromkeys(reading.unknown))
        report.warnings.append(
            f"読みを推定できなかった文字があります（{unknown}）。"
            "音数が実際と異なる可能性があるため `--yomi` で読みを与えてください。"
        )

    for seg in report.segments:
        if seg.delta > 0:
            report.warnings.append(
                f"{seg.name}が {seg.mora} 音で字余り（+{seg.delta}）です。"
                "意図的な破調なら効果を、そうでなければ語の圧縮を検討してください。"
            )
        elif seg.delta < 0:
            report.warnings.append(
                f"{seg.name}が {seg.mora} 音で字足らず（{seg.delta}）です。"
                "間として効かせるのでなければ音を補うことを検討してください。"
            )

    if report.total_mora and abs(report.total_mora - 17) >= 4:
        report.warnings.append(
            f"総音数 {report.total_mora} 音は定型（17 音）から大きく離れています。"
            "自由律を認めない大会では対象外になります。"
        )
    return report
