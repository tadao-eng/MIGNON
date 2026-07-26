"""③ 類似句・重複チェックモジュール。

二系統で照合する。

  1. ローカルの有名句コーパスとの文字列類似度（オフラインで常に動く）
  2. Web 検索 API（Tavily / Serper）による完全一致・部分一致の探索

結果を統合して「盗作・類句と疑われるリスク」を 4 段階で提示する。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum

import httpx

from . import kana as kana_util
from .db import FamousHaiku

# ローカル照合のしきい値（0.0〜1.0 の Dice 係数ベース）
THRESHOLD_HIGH = 0.85
THRESHOLD_MEDIUM = 0.70
THRESHOLD_REPORT = 0.55


class RiskLevel(str, Enum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"
    UNKNOWN = "判定不能"

    @property
    def advice(self) -> str:
        return {
            RiskLevel.HIGH: "そのままの投句は避けてください。既存句とほぼ同一か、著名句の措辞をなぞっています。",
            RiskLevel.MEDIUM: "既視感のある表現が含まれます。中七〜下五を中心に言い換えを検討してください。",
            RiskLevel.LOW: "現時点で明らかな類句は見つかりませんでした（網羅性は保証されません）。",
            RiskLevel.UNKNOWN: "照合材料が不足しています。Web 検索 API キーの設定をご検討ください。",
        }[self]


@dataclass
class LocalMatch:
    text: str
    author: str
    score: float
    shared: str  # 最長共通部分（かな）

    def to_dict(self) -> dict:
        return {"text": self.text, "author": self.author, "score": round(self.score, 3), "shared": self.shared}


@dataclass
class WebMatch:
    query: str
    title: str
    url: str
    snippet: str
    exact: bool

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet[:300],
            "exact": self.exact,
        }


@dataclass
class SimilarityReport:
    risk: RiskLevel = RiskLevel.UNKNOWN
    local_matches: list[LocalMatch] = field(default_factory=list)
    web_matches: list[WebMatch] = field(default_factory=list)
    web_provider: str | None = None
    web_error: str | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "risk": self.risk.value,
            "advice": self.risk.advice,
            "reasons": self.reasons,
            "local_matches": [m.to_dict() for m in self.local_matches],
            "web_provider": self.web_provider,
            "web_error": self.web_error,
            "web_matches": [m.to_dict() for m in self.web_matches],
        }


# --------------------------------------------------------------------- 文字列類似度


def _bigrams(s: str) -> set[str]:
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def dice_coefficient(a: str, b: str) -> float:
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return 0.0
    return 2 * len(ba & bb) / (len(ba) + len(bb))


def longest_common_substring(a: str, b: str) -> str:
    if not a or not b:
        return ""
    prev = [0] * (len(b) + 1)
    best_len = 0
    best_end = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best_len:
                    best_len = cur[j]
                    best_end = i
        prev = cur
    return a[best_end - best_len : best_end]


def similarity(a_kana: str, b_kana: str) -> tuple[float, str]:
    """Dice 係数と最長共通部分長を合成したスコアを返す。"""
    dice = dice_coefficient(a_kana, b_kana)
    lcs = longest_common_substring(a_kana, b_kana)
    lcs_ratio = len(lcs) / max(len(a_kana), 1)
    return max(dice, lcs_ratio * 0.95), lcs


def _plain(text: str) -> str:
    """空白と句読点・記号を落として比較用に正規化する。"""
    return "".join(
        ch for ch in kana_util.normalize(text) if not ch.isspace() and ch not in "。、，．「」『』・…ー－―"
    )


def compare(target_text: str, target_kana: str, entry_text: str, entry_kana: str) -> tuple[float, str]:
    """表記と読みの両面で比較し、高い方のスコアを採用する。

    「蛙」を「かわず」と読むか「かえる」と読むかで読みは割れるため、読みだけで
    比較すると原句の丸写しを取り逃がす。表記側の比較がその穴を塞ぐ。
    """
    kana_score, kana_shared = similarity(target_kana, entry_kana)
    text_score, text_shared = similarity(_plain(target_text), _plain(entry_text))
    if text_score >= kana_score:
        return text_score, text_shared
    return kana_score, kana_shared


# --------------------------------------------------------------------- Web 検索


class WebSearchError(RuntimeError):
    pass


def _search_tavily(query: str, api_key: str, timeout: float) -> list[dict]:
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "max_results": 5, "search_depth": "basic"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def _search_serper(query: str, api_key: str, timeout: float) -> list[dict]:
    resp = httpx.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "gl": "jp", "hl": "ja", "num": 5},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {"title": r.get("title", ""), "url": r.get("link", ""), "content": r.get("snippet", "")}
        for r in data.get("organic", [])
    ]


def detect_provider() -> tuple[str, str] | tuple[None, None]:
    """環境変数から利用可能な検索プロバイダを検出する。"""
    if key := os.environ.get("TAVILY_API_KEY"):
        return "tavily", key
    if key := os.environ.get("SERPER_API_KEY"):
        return "serper", key
    return None, None


def web_search(query: str, provider: str, api_key: str, timeout: float = 20.0) -> list[dict]:
    if provider == "tavily":
        return _search_tavily(query, api_key, timeout)
    if provider == "serper":
        return _search_serper(query, api_key, timeout)
    raise WebSearchError(f"未知の検索プロバイダ: {provider}")


# --------------------------------------------------------------------- 本体


def check(
    text: str,
    reading_kana: str,
    corpus: list[FamousHaiku],
    segments: list[str] | None = None,
    use_web: bool = True,
    provider: str | None = None,
    api_key: str | None = None,
) -> SimilarityReport:
    report = SimilarityReport()
    target_kana = kana_util.kana_only(reading_kana or text)

    # ---- 1. ローカルコーパス照合
    scored: list[LocalMatch] = []
    for entry in corpus:
        score, shared = compare(text, target_kana, entry.text, kana_util.kana_only(entry.kana))
        if score >= THRESHOLD_REPORT:
            scored.append(LocalMatch(entry.text, entry.author, score, shared))
    scored.sort(key=lambda m: m.score, reverse=True)
    report.local_matches = scored[:5]

    top = scored[0].score if scored else 0.0
    if top >= THRESHOLD_HIGH:
        report.risk = RiskLevel.HIGH
        report.reasons.append(
            f"既知の句「{scored[0].text}」（{scored[0].author}）と類似度 {top:.0%} です。"
        )
    elif top >= THRESHOLD_MEDIUM:
        report.risk = RiskLevel.MEDIUM
        report.reasons.append(
            f"既知の句「{scored[0].text}」（{scored[0].author}）と類似度 {top:.0%}、"
            f"共通部分「{scored[0].shared}」があります。"
        )
    else:
        report.risk = RiskLevel.LOW

    for m in scored[:3]:
        if len(m.shared) >= 5 and m.score < THRESHOLD_MEDIUM:
            report.reasons.append(
                f"「{m.shared}」は「{m.text}」（{m.author}）と共通する措辞です。類想と見なされる恐れがあります。"
            )

    # ---- 2. Web 検索
    if not use_web:
        return report

    if provider is None or api_key is None:
        provider, api_key = detect_provider()
    if not provider or not api_key:
        report.web_error = (
            "Web 検索 API キーが未設定のため、ネット上の類句照合はスキップしました"
            "（TAVILY_API_KEY または SERPER_API_KEY を設定してください）。"
        )
        if report.risk == RiskLevel.LOW:
            report.risk = RiskLevel.LOW
        return report

    report.web_provider = provider
    plain = text.replace(" ", "").replace("　", "")
    queries = [f'"{plain}"']
    for seg in (segments or [])[:3]:
        seg = seg.strip()
        if len(seg) >= 4:
            queries.append(f'"{seg}" 俳句')

    try:
        for query in queries:
            for result in web_search(query, provider, api_key):
                content = f"{result.get('title', '')} {result.get('content', '')}"
                normalized = content.replace(" ", "").replace("　", "")
                exact = plain in normalized
                report.web_matches.append(
                    WebMatch(
                        query=query,
                        title=result.get("title", ""),
                        url=result.get("url", ""),
                        snippet=result.get("content", ""),
                        exact=exact,
                    )
                )
    except httpx.HTTPError as exc:
        report.web_error = f"Web 検索に失敗しました: {exc}"
        return report

    if any(m.exact for m in report.web_matches):
        report.risk = RiskLevel.HIGH
        hit = next(m for m in report.web_matches if m.exact)
        report.reasons.append(f"入力句と完全一致する記述がネット上に存在します（{hit.url}）。")
    elif report.web_matches and report.risk == RiskLevel.LOW:
        # 上五・中七などフレーズ単位のヒットは「中」相当まで引き上げる。
        phrase_hits = [m for m in report.web_matches if m.query != f'"{plain}"']
        if len(phrase_hits) >= 3:
            report.risk = RiskLevel.MEDIUM
            report.reasons.append(
                "フレーズ単位で複数の既出用例が見つかりました。措辞が使い古されている可能性があります。"
            )
    return report
