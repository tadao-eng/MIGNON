"""3 モジュールを束ねる解析パイプライン。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from . import db, evaluator, saijiki as saijiki_mod, similarity, structure
from .reading import Reader, ReadingResult, get_reader, read_with_override


@dataclass
class AnalysisOptions:
    yomi: str | None = None
    target_season: str | None = None
    submission_date: date | None = None
    use_web: bool = True
    use_llm: bool = True
    model: str = evaluator.DEFAULT_MODEL
    effort: str = evaluator.DEFAULT_EFFORT
    data_dir: Path | None = None


@dataclass
class AnalysisResult:
    haiku: str
    reading: ReadingResult
    structure: structure.StructureReport
    saijiki: saijiki_mod.SaijikiReport
    similarity: similarity.SimilarityReport
    evaluation: evaluator.EvaluationResult | None

    def to_dict(self) -> dict:
        out = {
            "haiku": self.haiku,
            "reading": {
                "kana": self.reading.kana,
                "engine": self.reading.engine,
                "unknown": self.reading.unknown,
            },
            "structure": self.structure.to_dict(),
            "saijiki": self.saijiki.to_dict(),
            "similarity": self.similarity.to_dict(),
        }
        if self.evaluation is not None:
            out["evaluation"] = self.evaluation.to_dict()
        return out


def _structure_summary(report: structure.StructureReport) -> str:
    lines = [f"音数: {report.pattern}（計 {report.total_mora} 音）/ 定型: {'○' if report.is_teikei else '×'}"]
    for seg in report.segments:
        lines.append(f"- {seg.name}「{seg.text}」{seg.mora}音 [{seg.label}]")
    if report.kireji:
        lines.append("切字: " + "、".join(report.kireji))
    for w in report.warnings:
        lines.append(f"! {w}")
    return "\n".join(lines)


def _saijiki_summary(report: saijiki_mod.SaijikiReport) -> str:
    if report.muki:
        return "季語: 検出されず（無季の可能性）"
    lines = ["季語:"]
    for h in report.hits:
        lines.append(f"- {h.kigo.word}（{h.kigo.kana}／{h.season}・{h.kigo.category}）")
    lines.append(f"主たる季節: {report.primary_season}")
    if report.kigasanari:
        lines.append("季重なりあり")
    if report.kichigai:
        lines.append("季違いあり（異なる季節の季語が同居）")
    for w in report.warnings:
        lines.append(f"! {w}")
    for n in report.notes:
        lines.append(f"* {n}")
    return "\n".join(lines)


def _similarity_summary(report: similarity.SimilarityReport) -> str:
    lines = [f"類句リスク: {report.risk.value}"]
    for r in report.reasons:
        lines.append(f"- {r}")
    for m in report.local_matches[:3]:
        lines.append(f"- 近い既存句: 「{m.text}」（{m.author}）類似度 {m.score:.0%}")
    exact = [m for m in report.web_matches if m.exact]
    for m in exact[:3]:
        lines.append(f"- Web 完全一致: {m.url}")
    if report.web_error:
        lines.append(f"* {report.web_error}")
    return "\n".join(lines)


@lru_cache(maxsize=4)
def _resources(data_dir: Path | None) -> tuple[db.Saijiki, saijiki_mod.SaijikiMatcher, Reader]:
    """歳時記・照合器・リーダーは使い回す。

    サーバー用途では 1 リクエストごとに SQLite を読み直し、janome の辞書を
    ロードし直すのは無駄が大きい。CLI でも初回コストは変わらない。
    """
    data = db.load(data_dir)
    return data, saijiki_mod.SaijikiMatcher(data), get_reader(extra_dictionary=data.reading_dictionary())


def clear_cache() -> None:
    """歳時記データを更新したあとに呼ぶ。"""
    _resources.cache_clear()


def analyze(haiku: str, options: AnalysisOptions | None = None) -> AnalysisResult:
    options = options or AnalysisOptions()
    data, matcher, reader = _resources(options.data_dir)

    reading = read_with_override(haiku, options.yomi, reader)

    struct_report = structure.analyze(haiku, reading, reader=reader, user_yomi=options.yomi)

    saijiki_report = matcher.analyze(
        haiku,
        reading_kana=reading.kana,
        target_season=options.target_season,
        submission_date=options.submission_date,
        tokens=reading.tokens,
    )

    sim_report = similarity.check(
        haiku,
        reading.kana,
        data.famous,
        segments=[s.text for s in struct_report.segments],
        use_web=options.use_web,
    )

    evaluation = None
    if options.use_llm:
        evaluation = evaluator.evaluate(
            haiku,
            _structure_summary(struct_report),
            _saijiki_summary(saijiki_report),
            _similarity_summary(sim_report),
            reading=reading.kana,
            model=options.model,
            effort=options.effort,
        )

    return AnalysisResult(
        haiku=haiku,
        reading=reading,
        structure=struct_report,
        saijiki=saijiki_report,
        similarity=sim_report,
        evaluation=evaluation,
    )
