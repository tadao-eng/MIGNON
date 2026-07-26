from datetime import date

import pytest

from haiku_checker import db
from haiku_checker.saijiki import SaijikiMatcher


@pytest.fixture(scope="module")
def matcher():
    return SaijikiMatcher(db.load_json())


def test_detects_single_kigo(matcher):
    report = matcher.analyze("古池や蛙飛びこむ水の音")
    words = [h.kigo.word for h in report.hits]
    assert "蛙" in words
    assert report.primary_season == "春"
    assert not report.muki
    assert not report.kigasanari


def test_muki_when_no_kigo(matcher):
    report = matcher.analyze("まつすぐな道でさみしい")
    assert report.muki
    assert report.warnings


def test_kigasanari_same_season(matcher):
    # 桜（春・植物）と燕（春・動物）でどちらも春 → 季重なり
    report = matcher.analyze("桜散る燕の翼かすめけり")
    assert report.kigasanari
    assert not report.kichigai
    assert len(report.hits) >= 2


def test_kichigai_across_seasons(matcher):
    # 雪（冬）と向日葵（夏）
    report = matcher.analyze("雪の日の向日葵の絵を描きにけり")
    seasons = {h.season for h in report.hits}
    assert {"冬", "夏"} <= seasons
    assert report.kichigai


def test_out_of_season_against_target(matcher):
    report = matcher.analyze("雪の朝の駅", target_season="夏")
    assert report.out_of_season
    assert any("投句時期" in w for w in report.warnings)


def test_submission_date_infers_season(matcher):
    report = matcher.analyze("雪の朝の駅", submission_date=date(2026, 7, 1))
    assert report.target_season == "夏"
    assert report.out_of_season


def test_alias_matching(matcher):
    # 「小春日和」は「小春」の傍題で冬の季語
    report = matcher.analyze("小春日和の縁側に猫")
    assert any(h.kigo.word == "小春" for h in report.hits)
    assert report.primary_season == "冬"


def test_longest_match_prefers_specific_kigo(matcher):
    # 「秋の暮」を「秋」+「暮」に分解せず、一語として拾う
    report = matcher.analyze("この道や行く人なしに秋の暮")
    assert any(h.kigo.word == "秋の暮" for h in report.hits)


def test_note_surfaced_for_counterintuitive_kigo(matcher):
    report = matcher.analyze("朝顔の蔓の先まで日の当たる")
    assert any(h.kigo.word == "朝顔" for h in report.hits)
    assert any("朝顔" in n for n in report.notes)
