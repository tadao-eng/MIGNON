"""ターミナル向けの結果表示。"""

from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .analyzer import AnalysisResult
from .evaluator import AxisScore, Evaluation, Perspective
from .similarity import RiskLevel

RISK_STYLE = {
    RiskLevel.HIGH: "bold red",
    RiskLevel.MEDIUM: "bold yellow",
    RiskLevel.LOW: "green",
    RiskLevel.UNKNOWN: "dim",
}


def _score_style(score: int, maximum: int) -> str:
    ratio = score / maximum if maximum else 0
    if ratio >= 0.85:
        return "bold green"
    if ratio >= 0.7:
        return "green"
    if ratio >= 0.5:
        return "yellow"
    return "red"


def render(result: AnalysisResult, console: Console | None = None) -> None:
    console = console or Console()

    header = Text(result.haiku, style="bold cyan")
    if result.reading.kana:
        header.append(f"\n（{result.reading.kana}）", style="dim")
    console.print(Panel(header, title="評価対象", border_style="cyan"))

    _render_structure(result, console)
    _render_saijiki(result, console)
    _render_similarity(result, console)
    if result.evaluation is not None:
        _render_evaluation(result, console)


def _render_structure(result: AnalysisResult, console: Console) -> None:
    s = result.structure
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("句")
    table.add_column("本文")
    table.add_column("音数", justify="right")
    table.add_column("判定")
    for seg in s.segments:
        style = "green" if seg.delta == 0 else ("yellow" if abs(seg.delta) == 1 else "red")
        table.add_row(seg.name, seg.text, str(seg.mora), Text(seg.label, style=style))

    body: list = [table]
    verdict = Text()
    verdict.append(f"\n音数パターン {s.pattern}（計 {s.total_mora} 音）  ")
    verdict.append("定型" if s.is_teikei else "破調", style="green" if s.is_teikei else "yellow")
    if s.kireji:
        verdict.append("\n切字: " + "、".join(s.kireji), style="dim")
    if not s.confident:
        verdict.append("\n※ 音数の推定に不確実性があります", style="dim yellow")
    body.append(verdict)
    for w in s.warnings:
        body.append(Text(f"⚠ {w}", style="yellow"))

    console.print(Panel(Group(*body), title="1. 定型チェック", border_style="blue"))


def _render_saijiki(result: AnalysisResult, console: Console) -> None:
    r = result.saijiki
    body: list = []

    if r.muki:
        body.append(Text("季語が検出されませんでした（無季）", style="bold red"))
    else:
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("季語")
        table.add_column("読み")
        table.add_column("季節")
        table.add_column("分類")
        table.add_column("一致")
        for h in r.hits:
            season_style = "red" if (r.kichigai and h.season != r.primary_season) else "cyan"
            table.add_row(
                h.kigo.word,
                h.kigo.kana,
                Text(h.season, style=season_style),
                h.kigo.category,
                "本文" if h.matched_by == "surface" else "読み",
            )
        body.append(table)
        summary = Text(f"\n主たる季節: {r.primary_season}")
        if r.target_season:
            summary.append(f"　／　投句時期の季節: {r.target_season}")
        body.append(summary)

    for w in r.warnings:
        body.append(Text(f"⚠ {w}", style="yellow"))
    for n in r.notes:
        body.append(Text(f"ℹ {n}", style="dim"))

    console.print(Panel(Group(*body), title="2. 歳時記照合", border_style="blue"))


def _render_similarity(result: AnalysisResult, console: Console) -> None:
    r = result.similarity
    body: list = []
    risk = Text()
    risk.append("リスク度: ")
    risk.append(r.risk.value, style=RISK_STYLE[r.risk])
    body.append(risk)
    body.append(Text(r.risk.advice, style="dim"))

    for reason in r.reasons:
        body.append(Text(f"・{reason}"))

    if r.local_matches:
        table = Table(title="\n類似する既存句（ローカル照合）", show_header=True, header_style="bold", box=None)
        table.add_column("句")
        table.add_column("作者")
        table.add_column("類似度", justify="right")
        for m in r.local_matches:
            style = "red" if m.score >= 0.85 else ("yellow" if m.score >= 0.7 else "dim")
            table.add_row(m.text, m.author, Text(f"{m.score:.0%}", style=style))
        body.append(table)

    if r.web_matches:
        table = Table(title="\nWeb 検索結果", show_header=True, header_style="bold", box=None)
        table.add_column("完全一致", justify="center")
        table.add_column("タイトル")
        table.add_column("URL", overflow="fold")
        for m in r.web_matches[:6]:
            table.add_row(Text("●", style="red") if m.exact else "", m.title[:40], m.url)
        body.append(table)

    if r.web_error:
        body.append(Text(f"ℹ {r.web_error}", style="dim"))

    console.print(Panel(Group(*body), title="3. 類似句チェック", border_style="blue"))


def _axis_row(table: Table, label: str, axis: AxisScore) -> None:
    table.add_row(
        label,
        Text(f"{axis.score} / {axis.max_score}", style=_score_style(axis.score, axis.max_score)),
        axis.comment,
    )


def _perspective_panel(title: str, p: Perspective, border: str) -> Panel:
    body: list = [Text(p.verdict)]
    if p.strengths:
        body.append(Text("\n◎ 評価する点", style="bold green"))
        body.extend(Text(f"  ・{s}") for s in p.strengths)
    if p.concerns:
        body.append(Text("\n△ 気になる点", style="bold yellow"))
        body.extend(Text(f"  ・{c}") for c in p.concerns)
    body.append(Text(f"\n見込み: {p.estimated_grade}", style="bold"))
    return Panel(Group(*body), title=title, border_style=border)


def _render_evaluation(result: AnalysisResult, console: Console) -> None:
    ev = result.evaluation
    assert ev is not None

    if ev.evaluation is None:
        console.print(Panel(Text(ev.error or "評価を取得できませんでした", style="yellow"),
                            title="4. 客観的評価・添削", border_style="blue"))
        return

    e: Evaluation = ev.evaluation
    total_style = _score_style(e.total_score, 100)

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("観点")
    table.add_column("得点", justify="right")
    table.add_column("講評")
    _axis_row(table, "構造", e.structure)
    _axis_row(table, "オリジナリティ", e.originality)
    _axis_row(table, "情景・余韻", e.imagery)

    total = Text(f"\n総合スコア: {e.total_score} / 100", style=f"bold {total_style}")
    console.print(Panel(Group(table, total), title="4. 客観的評価", border_style="blue"))

    issues = [i for axis in (e.structure, e.originality, e.imagery) for i in axis.issues]
    if issues:
        console.print(Panel(Group(*[Text(f"・{i}") for i in issues]),
                            title="指摘事項", border_style="yellow"))

    console.print(_perspective_panel("5a. 伝統派（有季定型）の視点", e.traditional, "magenta"))
    console.print(_perspective_panel("5b. 現代派の視点", e.modern, "green"))

    if e.revisions:
        body: list = []
        for idx, rev in enumerate(e.revisions, start=1):
            body.append(Text(f"\n【案{idx}】{rev.haiku}", style="bold cyan"))
            body.append(Text(f"  変更点: {rev.changed}"))
            body.append(Text(f"  ねらい: {rev.intent}"))
            body.append(Text(f"  留意点: {rev.tradeoff}", style="dim"))
        console.print(Panel(Group(*body), title="6. 添削案", border_style="cyan"))

    console.print(Panel(Text(e.summary), title="総括", border_style="bold white"))
    if ev.usage:
        console.print(
            f"[dim]model={ev.model}  in={ev.usage['input_tokens']}tok  out={ev.usage['output_tokens']}tok[/dim]"
        )
