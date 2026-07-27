"""配布用 HTML の生成と、JS 移植版が Python 実装と一致するかの検証。

判定ロジックを JS に移植している以上、両者がずれれば配布版だけ誤った結果を出す。
ブラウザで実際に動かして突き合わせる。Playwright が無い環境ではスキップする。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from haiku_checker import artifact, db, saijiki as saijiki_mod, similarity, structure
from haiku_checker.reading import get_reader, read_with_override

# (句, 読み, 投句時期の季節)
CASES = [
    ("古池や 蛙飛びこむ 水の音", None, None),
    ("ふるいけや かわずとびこむ みずのおと", None, None),
    ("雪の日に 向日葵の絵を 描く", None, "夏"),
    ("桜散る燕の翼かすめけり", None, None),
    ("まつすぐな道でさみしい", None, None),
    ("万緑の 中や吾子の歯 生え初むる", "ばんりょくの なかやあこのは はえそむる", None),
    ("万緑の 中や吾子の歯 生え初むる", "ばんりょくのなかやあこのははえそむる", None),
    ("朝顔の蔓の先まで日の当たる", None, None),
    ("小春日和の縁側に猫", None, "春"),
    ("この道や行く人なしに秋の暮", None, None),
    ("柿くへば鐘が鳴るなり法隆寺", None, None),
    ("らーめんの湯気やがつこうの帰り道", None, None),
    ("非常口の緑の人と冬に入る", None, None),
    ("たんぽぽや ひはいつまでも おおぞらに", None, "秋"),
]

JS = """
([haiku, yomi, season]) => {
  const r = judge(haiku, yomi, season);
  return {
    kana: r.reading.kana,
    unknown: [...new Set(r.reading.unknown)].sort(),
    pattern: r.structure.pattern,
    total: r.structure.totalMora,
    teikei: r.structure.isTeikei,
    split: r.structure.splitSource,
    kireji: r.structure.kireji,
    kigo: r.saijiki.hits.map(h => h.kigo.w + "/" + h.kigo.s).sort(),
    muki: r.saijiki.muki,
    kigasanari: r.saijiki.kigasanari,
    kichigai: r.saijiki.kichigai,
    out: r.saijiki.outOfSeason.map(h => h.kigo.w).sort(),
    risk: r.similarity.risk,
  };
}
"""


def _python_result(haiku, yomi, season, data, reader, matcher):
    reading = read_with_override(haiku, yomi, reader)
    st = structure.analyze(haiku, reading, reader=reader, user_yomi=yomi)
    sj = matcher.analyze(
        haiku, reading_kana=reading.kana, target_season=season, tokens=reading.tokens
    )
    sm = similarity.check(haiku, reading.kana, data.famous, use_web=False)
    return {
        "kana": reading.kana,
        "unknown": sorted(set(reading.unknown)),
        "pattern": st.pattern,
        "total": st.total_mora,
        "teikei": st.is_teikei,
        "split": st.split_source,
        "kireji": st.kireji,
        "kigo": sorted(f"{h.kigo.word}/{h.season}" for h in sj.hits),
        "muki": sj.muki,
        "kigasanari": sj.kigasanari,
        "kichigai": sj.kichigai,
        "out": sorted(h.kigo.word for h in sj.out_of_season),
        "risk": sm.risk.value,
    }


def test_build_produces_self_contained_html(tmp_path):
    out = artifact.build(tmp_path / "a.html")
    html = out.read_text(encoding="utf-8")
    assert artifact.PLACEHOLDER not in html, "データが埋め込まれていない"
    # 外部リソースを読まないこと（CSP でブロックされ、静かに壊れるため）。
    # 唯一の例外は AI評価が使う Gemini のエンドポイントで、これは利用者の
    # 明示操作（キー入力＋ボタン押下）でのみ発火する意図的な通信。
    stripped = (
        html.replace('xmlns="http', "")
        .replace("https://generativelanguage.googleapis.com/", "")
    )
    assert "http://" not in stripped and "https://" not in stripped
    assert "季語" in html


def test_reading_dictionary_matches_python():
    """読み辞書が Python 側と同一であること。

    ここがずれると配布版と CLI で音数が食い違う。傍題を足すと
    見出し語の読みで代用することになり誤る（小春日和 → こはる）。
    """
    from haiku_checker.reading import BUILTIN_READINGS

    payload = artifact.build_payload()
    expected = {**BUILTIN_READINGS, **db.load_json().reading_dictionary()}
    assert payload["readings"] == expected
    assert "小春日和" not in payload["readings"]


def test_js_matches_python(tmp_path):
    sync_playwright = pytest.importorskip(
        "playwright.sync_api", reason="Playwright 未インストール"
    ).sync_playwright

    html = artifact.build(tmp_path / "a.html")
    data = db.load_json()
    # JS 側は形態素解析を持たないので、Python も内蔵辞書リーダーに揃える
    reader = get_reader(extra_dictionary=data.reading_dictionary(), prefer="dictionary")
    matcher = saijiki_mod.SaijikiMatcher(data)

    errors: list[str] = []
    mismatches: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(pathlib.Path(html).resolve().as_uri())
        assert not errors, f"ページ読み込みで JS エラー: {errors}"

        for haiku, yomi, season in CASES:
            want = _python_result(haiku, yomi, season, data, reader, matcher)
            got = page.evaluate(JS, [haiku, yomi, season])
            for key in want:
                if want[key] != got[key]:
                    mismatches.append(f"{haiku} / {key}: python={want[key]!r} js={got[key]!r}")
        browser.close()

    assert not mismatches, "JS 移植が Python と一致しません:\n" + "\n".join(mismatches)


# ══ AI評価（Gemini） ══════════════════════════════════════════
# window.fetch をスタブして、公開ページから Gemini を叩くフローを検証する。
# 実キー・実通信は使わない。ダミーキーは明らかな偽物にする。
DUMMY_KEY = "dummy-key-for-test"

SAMPLE_EVALUATION = {
    "total_score": 78,
    "structure": {"score": 24, "max_score": 30, "comment": "破調が効いている。", "issues": []},
    "originality": {"score": 27, "max_score": 35, "comment": "類想がやや強い。", "issues": ["類想の懸念"]},
    "imagery": {"score": 27, "max_score": 35, "comment": "像は鮮明。", "issues": []},
    "traditional": {
        "verdict": "有季定型としては十分に整っている。",
        "strengths": ["季語の斡旋が的確"],
        "concerns": [],
        "estimated_grade": "予選通過圏",
    },
    "modern": {
        "verdict": "破調の必然性がやや薄い。",
        "strengths": [],
        "concerns": ["説明的になっている部分がある"],
        "estimated_grade": "要推敲",
    },
    "revisions": [
        {
            "haiku": "テスト 添削の 一句かな",
            "changed": "中七を言い換えた。",
            "intent": "具体性を上げるため。",
            "tradeoff": "字余りになる。",
        }
    ],
    "summary": "推敲の余地はあるが、投句可能な水準にある。",
}


@pytest.fixture(scope="module")
def sync_playwright_module():
    return pytest.importorskip(
        "playwright.sync_api", reason="Playwright 未インストール"
    ).sync_playwright


@pytest.fixture(scope="module")
def ai_browser(sync_playwright_module):
    with sync_playwright_module() as p:
        browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def ai_html_uri(tmp_path_factory):
    out = artifact.build(tmp_path_factory.mktemp("ai-artifact") / "a.html")
    return pathlib.Path(out).resolve().as_uri()


def _open_with_fetch_stub(ai_browser, ai_html_uri, stub_js):
    """window.fetch を stub_js のスクリプトで差し替えたページを開いて返す。"""
    page = ai_browser.new_page()
    page.add_init_script(stub_js)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(ai_html_uri)
    assert not errors, f"ページ読み込みで JS エラー: {errors}"
    return page


def _run_ai_eval(page, haiku="古池や 蛙飛びこむ 水の音", key=DUMMY_KEY):
    page.fill("#haiku", haiku)
    page.fill("#geminiKey", key)
    page.click("#geminiRun")


def test_ai_success_shows_score_and_perspectives(ai_browser, ai_html_uri):
    """1. 成功系: スキーマ通りのJSONを返すスタブ → 総合スコア・両派の講評・添削案が画面に出ること。"""
    stub = f"""
    window.fetch = async (url, init) => {{
      window.__capturedInit = init;
      const body = {json.dumps(json.dumps({
          "candidates": [{
              "content": {"parts": [{"text": json.dumps(SAMPLE_EVALUATION, ensure_ascii=False)}]},
              "finishReason": "STOP",
          }]
      }))};
      return new Response(body, {{ status: 200, headers: {{ "Content-Type": "application/json" }} }});
    }};
    """
    page = _open_with_fetch_stub(ai_browser, ai_html_uri, stub)
    try:
        _run_ai_eval(page)
        page.wait_for_selector("#aiOut .ai-score")
        text = page.inner_text("#aiOut")
        assert "78 / 100" in text
        assert "総合スコア" in text
        assert SAMPLE_EVALUATION["traditional"]["verdict"] in text
        assert SAMPLE_EVALUATION["modern"]["verdict"] in text
        assert SAMPLE_EVALUATION["revisions"][0]["haiku"] in text
        assert SAMPLE_EVALUATION["summary"] in text
    finally:
        page.close()


def test_ai_network_failure(ai_browser, ai_html_uri):
    """2. 通信断: fetch が reject → 「通信できませんでした」が出ること。"""
    stub = """
    window.fetch = async () => { throw new TypeError("Failed to fetch"); };
    """
    page = _open_with_fetch_stub(ai_browser, ai_html_uri, stub)
    try:
        _run_ai_eval(page)
        page.wait_for_selector("#aiOut .alert")
        text = page.inner_text("#aiOut")
        assert "通信できませんでした" in text
    finally:
        page.close()


def test_ai_invalid_key(ai_browser, ai_html_uri):
    """3. キー不正: 400 + API_KEY_INVALID → キーの文言が出ること。"""
    error_body = {
        "error": {
            "code": 400,
            "message": "API key not valid. Please pass a valid API key. [API_KEY_INVALID]",
        }
    }
    stub = f"""
    window.fetch = async () => new Response({json.dumps(json.dumps(error_body))}, {{ status: 400 }});
    """
    page = _open_with_fetch_stub(ai_browser, ai_html_uri, stub)
    try:
        _run_ai_eval(page)
        page.wait_for_selector("#aiOut .alert")
        text = page.inner_text("#aiOut")
        assert "APIキーが正しくありません" in text
    finally:
        page.close()


def test_ai_quota_exceeded(ai_browser, ai_html_uri):
    """4. 無料枠超過: 429 → 上限の文言が出ること、かつ「課金は発生しません」が含まれること。"""
    error_body = {"error": {"code": 429, "message": "Resource has been exhausted."}}
    stub = f"""
    window.fetch = async () => new Response({json.dumps(json.dumps(error_body))}, {{ status: 429 }});
    """
    page = _open_with_fetch_stub(ai_browser, ai_html_uri, stub)
    try:
        _run_ai_eval(page)
        page.wait_for_selector("#aiOut .alert")
        text = page.inner_text("#aiOut")
        assert "無料枠の上限に達しました" in text
        assert "課金は発生しません" in text
    finally:
        page.close()


def test_ai_broken_json(ai_browser, ai_html_uri):
    """5. 壊れたJSON: 200 だが本文が "{{{" → 読み取れない旨が出ること。"""
    envelope = {
        "candidates": [{"content": {"parts": [{"text": "{{{"}]}, "finishReason": "STOP"}]
    }
    stub = f"""
    window.fetch = async () => new Response({json.dumps(json.dumps(envelope))}, {{ status: 200 }});
    """
    page = _open_with_fetch_stub(ai_browser, ai_html_uri, stub)
    try:
        _run_ai_eval(page)
        page.wait_for_selector("#aiOut .alert")
        text = page.inner_text("#aiOut")
        assert "評価結果を読み取れませんでした" in text
    finally:
        page.close()


def test_ai_key_sent_in_header(ai_browser, ai_html_uri):
    """6. キーが送信ヘッダに載ること — スタブが受け取った x-goog-api-key が入力値と一致すること。"""
    stub = f"""
    window.fetch = async (url, init) => {{
      window.__capturedUrl = url;
      window.__capturedInit = init;
      const body = {json.dumps(json.dumps({
          "candidates": [{
              "content": {"parts": [{"text": json.dumps(SAMPLE_EVALUATION, ensure_ascii=False)}]},
              "finishReason": "STOP",
          }]
      }))};
      return new Response(body, {{ status: 200, headers: {{ "Content-Type": "application/json" }} }});
    }};
    """
    page = _open_with_fetch_stub(ai_browser, ai_html_uri, stub)
    try:
        _run_ai_eval(page)
        page.wait_for_selector("#aiOut .ai-score")
        sent_key = page.evaluate("window.__capturedInit.headers['x-goog-api-key']")
        assert sent_key == DUMMY_KEY
        sent_url = page.evaluate("window.__capturedUrl")
        assert "key=" not in sent_url  # クエリパラメータ ?key= は使わない
    finally:
        page.close()


def test_ai_key_not_embedded_in_generated_html(tmp_path):
    """7. キーがHTMLに埋まっていないこと — 生成後の index.html に実キーらしき文字列が無いこと。"""
    out = artifact.build(tmp_path / "index.html")
    html = out.read_text(encoding="utf-8")
    assert "AIza" not in html
    assert "x-goog-api-key: " not in html
    assert DUMMY_KEY not in html


def test_ai_section_absent_in_bare_build(ai_browser, tmp_path):
    """8. bare ではセクションが出ないこと — build(bare=True) に AI評価セクションが生成されないこと。

    bare の出力は文書骨格(<html>/<body>)を持たない断片なので、検証用に最小限の
    シェルで包んでから読み込む。JS 本体は bare/非bare で共通なので、raw な文字列
    検索では判定できない（`if (DATA.ai) {...}` の中身自体はソースとして残るため）。
    DATA.ai=False では「その中身が実行されずセクションが DOM に生成されない」ことが
    検証すべき点なので、実ブラウザで DOM を確認する。
    """
    fragment = artifact.build(tmp_path / "bare.html", bare=True).read_text(encoding="utf-8")
    assert 'id="aiSection"' not in fragment  # 静的マークアップとしては最初から存在しない
    wrapped_path = tmp_path / "bare_wrapped.html"
    wrapped_path.write_text(f"<!doctype html><html><body>{fragment}</body></html>", encoding="utf-8")

    page = ai_browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(wrapped_path.resolve().as_uri())
    assert not errors, f"ページ読み込みで JS エラー: {errors}"
    try:
        assert page.query_selector("#aiSection") is None
        assert page.query_selector("#geminiKey") is None
        assert page.query_selector("#geminiRun") is None
    finally:
        page.close()
