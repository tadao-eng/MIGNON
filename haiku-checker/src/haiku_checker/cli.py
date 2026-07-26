"""コマンドラインインターフェース。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from rich.console import Console

from . import db, evaluator
from .analyzer import AnalysisOptions, analyze
from .report import render

SEASONS = ("春", "夏", "秋", "冬", "新年")


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日付は YYYY-MM-DD 形式で指定してください") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="haiku",
        description="自作俳句の推敲・評価・類句チェックツール",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="俳句を総合的に評価する")
    check.add_argument("haiku", nargs="?", help="評価する句（省略時は標準入力から読む）")
    check.add_argument(
        "--yomi",
        help="句の読み（かな）。漢字の読みが推定できない場合に指定する。"
             "上五／中七／下五をスペースで区切ると各節の音数まで正確に判定できる",
    )
    check.add_argument("--season", choices=SEASONS, help="投句先が想定する季節（季節外れ判定に使う）")
    check.add_argument("--date", type=_parse_date, dest="submission_date",
                       help="投句日 YYYY-MM-DD。--season 未指定時にこの月から季節を推定")
    check.add_argument("--no-web", action="store_true", help="Web 検索による類句チェックを行わない")
    check.add_argument("--no-llm", action="store_true", help="LLM による評価・添削を行わない")
    check.add_argument("--model", default=evaluator.DEFAULT_MODEL, help="評価に使うモデル ID")
    check.add_argument("--effort", default=evaluator.DEFAULT_EFFORT,
                       choices=["low", "medium", "high", "xhigh", "max"], help="思考の深さ")
    check.add_argument("--json", action="store_true", dest="as_json", help="結果を JSON で出力")
    check.add_argument("--data-dir", type=Path, help="歳時記データのディレクトリ")

    batch = sub.add_parser("batch", help="ファイル内の複数句をまとめて評価（1行1句）")
    batch.add_argument("path", type=Path, help="句を並べたテキストファイル")
    batch.add_argument("--season", choices=SEASONS)
    batch.add_argument("--no-web", action="store_true")
    batch.add_argument("--no-llm", action="store_true")
    batch.add_argument("--model", default=evaluator.DEFAULT_MODEL)
    batch.add_argument("--json", action="store_true", dest="as_json")
    batch.add_argument("--data-dir", type=Path)

    builddb = sub.add_parser("build-db", help="JSON から歳時記 SQLite を再構築する")
    builddb.add_argument("--data-dir", type=Path)

    serve = sub.add_parser("serve", help="ブラウザから使う Web アプリを起動する")
    serve.add_argument("--host", default="127.0.0.1",
                       help="待ち受けアドレス（既定は自分の端末からのみ）")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="開発用のオートリロード")

    kigo = sub.add_parser("kigo", help="季語を検索する")
    kigo.add_argument("query", nargs="?", help="部分一致で検索する語")
    kigo.add_argument("--season", choices=SEASONS)
    kigo.add_argument("--category")
    kigo.add_argument("--data-dir", type=Path)

    return parser


def cmd_check(args, console: Console) -> int:
    haiku = args.haiku
    if not haiku:
        haiku = sys.stdin.read().strip()
    if not haiku:
        console.print("[red]評価する句が空です。[/red]")
        return 1

    options = AnalysisOptions(
        yomi=args.yomi,
        target_season=args.season,
        submission_date=args.submission_date,
        use_web=not args.no_web,
        use_llm=not args.no_llm,
        model=args.model,
        effort=args.effort,
        data_dir=args.data_dir,
    )
    result = analyze(haiku, options)

    if args.as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        render(result, console)
    return 0


def cmd_batch(args, console: Console) -> int:
    if not args.path.exists():
        console.print(f"[red]ファイルが見つかりません: {args.path}[/red]")
        return 1
    lines = [l.strip() for l in args.path.read_text(encoding="utf-8").splitlines()]
    haikus = [l for l in lines if l and not l.startswith("#")]
    if not haikus:
        console.print("[yellow]評価対象の句がありません。[/yellow]")
        return 1

    options = AnalysisOptions(
        target_season=args.season,
        use_web=not args.no_web,
        use_llm=not args.no_llm,
        model=args.model,
        data_dir=args.data_dir,
    )
    results = []
    for idx, haiku in enumerate(haikus, start=1):
        if not args.as_json:
            console.rule(f"[bold]{idx}/{len(haikus)}")
        result = analyze(haiku, options)
        if args.as_json:
            results.append(result.to_dict())
        else:
            render(result, console)

    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def cmd_build_db(args, console: Console) -> int:
    path = db.build_db(args.data_dir)
    data = db.load(args.data_dir)
    console.print(f"[green]構築しました:[/green] {path}")
    console.print(f"  季語 {len(data.kigo)} 件 / 有名句 {len(data.famous)} 件")
    return 0


def cmd_serve(args, console: Console) -> int:
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        console.print("[red]Web アプリの依存が未インストールです。[/red] pip install -e \".[web]\"")
        return 1

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        console.print(
            f"[yellow]警告: {args.host} で待ち受けます。[/yellow] "
            "このアプリに認証はありません。到達できる相手は誰でもあなたの Anthropic API キーで "
            "評価を実行できます（= あなたに課金されます）。外部に出す場合は必ず前段に認証を置いてください。"
        )

    console.print(f"[green]起動しました:[/green] http://{args.host}:{args.port}/")
    import uvicorn

    uvicorn.run(
        "haiku_checker.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


def cmd_kigo(args, console: Console) -> int:
    data = db.load(args.data_dir)
    rows = data.kigo
    if args.season:
        rows = [k for k in rows if k.season == args.season]
    if args.category:
        rows = [k for k in rows if k.category == args.category]
    if args.query:
        q = args.query
        rows = [k for k in rows if q in k.word or q in k.kana or any(q in a for a in k.aliases)]

    if not rows:
        console.print("[yellow]該当する季語はありません。[/yellow]")
        return 1

    from rich.table import Table

    table = Table(show_header=True, header_style="bold")
    table.add_column("季語")
    table.add_column("読み")
    table.add_column("季節")
    table.add_column("分類")
    table.add_column("傍題・備考", overflow="fold")
    for k in rows[:100]:
        extra = "、".join(k.aliases)
        if k.note:
            extra = f"{extra}（{k.note}）" if extra else k.note
        table.add_row(k.word, k.kana, k.season, k.category, extra)
    console.print(table)
    if len(rows) > 100:
        console.print(f"[dim]… 他 {len(rows) - 100} 件[/dim]")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console()

    handlers = {
        "check": cmd_check,
        "batch": cmd_batch,
        "build-db": cmd_build_db,
        "kigo": cmd_kigo,
        "serve": cmd_serve,
    }
    return handlers[args.command](args, console)


if __name__ == "__main__":
    raise SystemExit(main())
