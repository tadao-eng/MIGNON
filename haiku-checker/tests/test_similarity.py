import pytest

from haiku_checker import db
from haiku_checker.similarity import (
    RiskLevel,
    dice_coefficient,
    longest_common_substring,
    check,
)


@pytest.fixture(scope="module")
def corpus():
    return db.load_json().famous


def test_dice_identical_and_disjoint():
    assert dice_coefficient("あいうえお", "あいうえお") == 1.0
    assert dice_coefficient("あいうえお", "かきくけこ") == 0.0


def test_longest_common_substring():
    assert longest_common_substring("ふるいけやかわず", "あたらしいけやかわず") == "いけやかわず"
    assert longest_common_substring("あいう", "かきく") == ""


def test_exact_copy_is_high_risk(corpus):
    report = check(
        "古池や蛙飛びこむ水の音",
        "ふるいけやかわずとびこむみずのおと",
        corpus,
        use_web=False,
    )
    assert report.risk is RiskLevel.HIGH
    assert report.local_matches[0].author == "松尾芭蕉"


def test_near_copy_is_flagged(corpus):
    report = check(
        "古池や蛙飛びこむ水の色",
        "ふるいけやかわずとびこむみずのいろ",
        corpus,
        use_web=False,
    )
    assert report.risk in (RiskLevel.HIGH, RiskLevel.MEDIUM)
    assert report.reasons


def test_original_haiku_is_low_risk(corpus):
    report = check(
        "非常口の緑の人と冬に入る",
        "ひじょうぐちのみどりのひとと ふゆにいる",
        corpus,
        use_web=False,
    )
    assert report.risk is RiskLevel.LOW


def test_web_disabled_does_not_error(corpus):
    report = check("test", "てすと", corpus, use_web=False)
    assert report.web_provider is None
    assert report.web_error is None
