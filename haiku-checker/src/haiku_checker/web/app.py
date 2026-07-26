"""FastAPI バックエンド。

CLI と同じ解析モジュールをそのまま使う。API キーはサーバー側にのみ置き、
フロントエンドには一切渡さない。

解析は 2 段階に分ける。定型・歳時記・ローカル類句照合は即座に返り、時間のかかる
LLM 評価は別エンドポイントにしてある（画面をブロックさせないため）。
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .. import __version__, db, evaluator, similarity
from ..analyzer import AnalysisOptions, analyze

STATIC_DIR = Path(__file__).parent / "static"

SEASONS = ("春", "夏", "秋", "冬", "新年")


class AnalyzeRequest(BaseModel):
    haiku: str = Field(min_length=1, max_length=200)
    yomi: str | None = Field(default=None, max_length=200)
    season: str | None = None
    date: str | None = None
    use_web: bool = True


class EvaluateRequest(AnalyzeRequest):
    model: str = evaluator.DEFAULT_MODEL
    effort: str = evaluator.DEFAULT_EFFORT


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日付は YYYY-MM-DD 形式で指定してください")


def _options(req: AnalyzeRequest, use_llm: bool, **extra) -> AnalysisOptions:
    if req.season and req.season not in SEASONS:
        raise HTTPException(status_code=400, detail=f"季節は {'/'.join(SEASONS)} のいずれかです")
    return AnalysisOptions(
        yomi=req.yomi or None,
        target_season=req.season,
        submission_date=_parse_date(req.date),
        use_web=req.use_web,
        use_llm=use_llm,
        **extra,
    )


def create_app() -> FastAPI:
    app = FastAPI(title="haiku-checker", version=__version__, docs_url="/api/docs")

    @app.get("/api/status")
    def status() -> dict:
        """フロントが機能の有効・無効を出し分けるための情報。キー自体は返さない。"""
        provider, _ = similarity.detect_provider()
        data = db.load()
        return {
            "version": __version__,
            "llm_available": bool(
                os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            ),
            "web_search_provider": provider,
            "default_model": evaluator.DEFAULT_MODEL,
            "kigo_count": len(data.kigo),
            "corpus_count": len(data.famous),
            "seasons": list(SEASONS),
        }

    @app.post("/api/analyze")
    def api_analyze(req: AnalyzeRequest) -> dict:
        """定型・歳時記・類句チェック（LLM 抜き）。数百 ms で返る。"""
        result = analyze(req.haiku.strip(), _options(req, use_llm=False))
        return result.to_dict()

    @app.post("/api/evaluate")
    def api_evaluate(req: EvaluateRequest) -> dict:
        """LLM による評価・添削。モデルの思考を含むため数十秒〜数分かかる。"""
        if req.effort not in ("low", "medium", "high", "xhigh", "max"):
            raise HTTPException(status_code=400, detail="effort の指定が不正です")
        options = _options(req, use_llm=True, model=req.model, effort=req.effort)
        result = analyze(req.haiku.strip(), options)
        if result.evaluation is None:
            raise HTTPException(status_code=500, detail="評価を実行できませんでした")
        return result.evaluation.to_dict()

    @app.get("/api/kigo")
    def api_kigo(q: str | None = None, season: str | None = None,
                 category: str | None = None, limit: int = 50) -> dict:
        data = db.load()
        rows = data.kigo
        if season:
            rows = [k for k in rows if k.season == season]
        if category:
            rows = [k for k in rows if k.category == category]
        if q:
            rows = [k for k in rows if q in k.word or q in k.kana or any(q in a for a in k.aliases)]
        return {
            "total": len(rows),
            "items": [
                {
                    "word": k.word,
                    "kana": k.kana,
                    "season": k.season,
                    "category": k.category,
                    "aliases": list(k.aliases),
                    "note": k.note,
                }
                for k in rows[: max(1, min(limit, 200))]
            ],
        }

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.svg")
    def favicon() -> Response:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
            '<rect width="32" height="32" rx="6" fill="#7a5c3e"/>'
            '<text x="16" y="23" font-size="20" text-anchor="middle" fill="#fff"'
            ' font-family="serif">句</text></svg>'
        )
        return Response(content=svg, media_type="image/svg+xml")

    return app


app = create_app()
