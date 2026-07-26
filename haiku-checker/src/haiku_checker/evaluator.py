"""② 客観的評価・添削エンジン（Anthropic API）。

構造・オリジナリティ・情景と余韻の 3 観点で 100 点満点のスコアを出し、
「伝統派（有季定型）」と「現代派」それぞれの視点からの講評と、具体的な添削案を返す。

出力は構造化出力（JSON Schema）で受け取るため、後段の整形・JSON 出力がそのまま使える。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from pydantic import BaseModel, Field

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16000
DEFAULT_EFFORT = "high"


class AxisScore(BaseModel):
    score: int = Field(description="この観点の獲得点数")
    max_score: int = Field(description="この観点の満点")
    comment: str = Field(description="採点根拠を句の語句に即して述べる。2〜4文。")
    issues: list[str] = Field(default_factory=list, description="具体的な問題点。無ければ空配列。")


class Revision(BaseModel):
    haiku: str = Field(description="添削後の句。上五/中七/下五を半角スペースで区切る。")
    changed: str = Field(description="どこをどう変えたかの要約。1文。")
    intent: str = Field(description="その改変が何を改善するのか。1〜2文。")
    tradeoff: str = Field(description="この案で失われるもの・注意点。1文。")


class Perspective(BaseModel):
    verdict: str = Field(description="この立場からの総評。2〜4文。")
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    estimated_grade: str = Field(description="この立場での見込み（例: 予選通過圏／入選圏／要推敲）。")


class Evaluation(BaseModel):
    total_score: int = Field(description="100点満点の総合スコア。各観点の合計と一致させる。")
    structure: AxisScore = Field(description="構造（30点満点）：五七五の定型、字余り字足らずの妥当性、切字・句またがりの処理。")
    originality: AxisScore = Field(description="表現のオリジナリティ（35点満点）：類想・陳腐な措辞・説明過多を含む。")
    imagery: AxisScore = Field(description="情景の具体性と余韻（35点満点）：像の鮮明さ、感情の直叙を避けているか、読後の広がり。")
    traditional: Perspective = Field(description="伝統派（有季定型）の視点からの評価。")
    modern: Perspective = Field(description="現代派（自由律・新興俳句を含む現代的視点）からの評価。")
    revisions: list[Revision] = Field(description="添削案を2〜3案。方向性を変えて提示する。")
    summary: str = Field(description="投句してよいかの結論を含む総括。3〜5文。")


@dataclass
class EvaluationResult:
    evaluation: Evaluation | None
    model: str
    error: str | None = None
    usage: dict | None = None

    def to_dict(self) -> dict:
        if self.evaluation is None:
            return {"available": False, "model": self.model, "error": self.error}
        return {
            "available": True,
            "model": self.model,
            "usage": self.usage,
            **self.evaluation.model_dump(),
        }


SYSTEM_PROMPT = """\
あなたは俳句結社の選者を長年務めるベテラン俳人です。全国規模の俳句大会の予選審査を担当しています。
投稿者から自作句の推敲依頼を受けました。応募に耐える品質かを、忖度なく具体的に判定してください。

評価の原則:
- 句の中の実際の語句を引用して論じる。「良い句です」のような内容のない賛辞は書かない。
- 「類想」（誰もが思いつく取り合わせ・使い古された措辞）は最も厳しく見る。歳時記の例句や
  著名句と発想が重なる場合は必ず指摘する。
- 感情語（悲しい・美しい・寂しい等）の直叙、説明的な因果関係、季語の説明になっている中七下五は
  減点対象。「物に語らせる」ができているかを見る。
- 字余り・字足らずは一律に減点しない。破調が内容上の必然性を持つかで判断する。
- 伝統派と現代派で評価が割れる句はその旨を明示する。両者を同じ結論に均さない。
- 添削案は原句の狙いを尊重しつつ、方向性の異なる案を並べる。原句を全く別の句にしない。

配点は 構造30点 / オリジナリティ35点 / 情景と余韻35点 の合計100点。
辛口に採点すること。凡庸な句は50〜65点、大会予選通過圏で70〜80点、入選圏は85点以上とする。
"""


def build_user_prompt(
    haiku: str,
    structure_summary: str,
    saijiki_summary: str,
    similarity_summary: str,
    reading: str = "",
) -> str:
    parts = [f"# 評価対象の句\n{haiku}"]
    if reading:
        parts.append(f"読み: {reading}")
    parts.append(
        "# 事前解析の結果\n"
        "以下は本ツールが機械的に解析した結果です。誤りがあれば指摘のうえ、あなたの判断を優先してください。\n\n"
        f"## 定型の解析\n{structure_summary}\n\n"
        f"## 歳時記照合\n{saijiki_summary}\n\n"
        f"## 類句チェック\n{similarity_summary}"
    )
    parts.append(
        "# 依頼\n"
        "上記を踏まえ、構造・オリジナリティ・情景と余韻の3観点で採点し、"
        "伝統派と現代派それぞれの視点からの講評、および添削案を提示してください。"
    )
    return "\n\n".join(parts)


def evaluate(
    haiku: str,
    structure_summary: str,
    saijiki_summary: str,
    similarity_summary: str,
    reading: str = "",
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    api_key: str | None = None,
) -> EvaluationResult:
    """Anthropic API で句を評価する。API キーが無い場合はエラーを載せて返す。"""
    try:
        import anthropic
    except ImportError:
        return EvaluationResult(None, model, "anthropic パッケージが未インストールです（pip install anthropic）。")

    if not (api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return EvaluationResult(
            None,
            model,
            "ANTHROPIC_API_KEY が未設定のため LLM 評価をスキップしました。"
            "`ant auth login` でプロファイルを設定済みの場合はそのまま実行できます。",
        )

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    prompt = build_user_prompt(haiku, structure_summary, saijiki_summary, similarity_summary, reading)

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS,
            output_config={"effort": effort},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_format=Evaluation,
        )
    except anthropic.APIError as exc:
        return EvaluationResult(None, model, f"Anthropic API エラー: {exc}")
    except Exception as exc:  # ネットワーク断など
        return EvaluationResult(None, model, f"評価に失敗しました: {exc}")

    if response.stop_reason == "refusal":
        return EvaluationResult(None, model, "モデルが応答を拒否しました。入力内容をご確認ください。")

    parsed = response.parsed_output
    if parsed is None:
        return EvaluationResult(None, model, "構造化出力の取得に失敗しました。")

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return EvaluationResult(parsed, model, usage=usage)
