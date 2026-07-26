"""配布用 HTML の生成と、JS 移植版が Python 実装と一致するかの検証。

判定ロジックを JS に移植している以上、両者がずれれば配布版だけ誤った結果を出す。
ブラウザで実際に動かして突き合わせる。Playwright が無い環境ではスキップする。
"""

from __future__ import annotations

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
    sj = matcher.analyze(haiku, reading_kana=reading.kana, target_season=season)
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
    # 外部リソースを読まないこと（CSP でブロックされ、静かに壊れるため）
    assert "http://" not in html and "https://" not in html.replace('xmlns="http', "")
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
