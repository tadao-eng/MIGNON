from haiku_checker import db, structure
from haiku_checker.reading import get_reader, read_with_override


def _analyze(text, yomi=None):
    data = db.load_json()
    reader = get_reader(extra_dictionary=data.reading_dictionary())
    reading = read_with_override(text, yomi, reader)
    return structure.analyze(text, reading, reader=reader, user_yomi=yomi)


def test_explicit_split_is_teikei():
    report = _analyze("ふるいけや かわずとびこむ みずのおと")
    assert report.split_source == "explicit"
    assert report.pattern == "5・7・5"
    assert report.is_teikei
    assert not report.warnings


def test_jiamari_detected():
    report = _analyze("ふるいけやや かわずとびこむ みずのおと")
    assert not report.is_teikei
    assert report.segments[0].delta == 1
    assert report.segments[0].label == "字余り+1"
    assert any("字余り" in w for w in report.warnings)


def test_jitarazu_detected():
    report = _analyze("ふるいけ かわずとびこむ みずのおと")
    assert report.segments[0].delta == -1
    assert "字足らず" in report.segments[0].label


def test_kireji_detected():
    report = _analyze("ふるいけや かわずとびこむ みずのおと")
    assert any("や" in k for k in report.kireji)

    report2 = _analyze("とおやまに ひのあたりたる かれのかな")
    assert any("かな" in k for k in report2.kireji)


def test_total_mora_far_from_17_warns():
    report = _analyze("せきをしても ひとり")
    assert report.total_mora < 14
    assert any("定型" in w or "17" in w for w in report.warnings)


def test_yomi_override_used_for_kanji():
    report = _analyze("古池や蛙飛びこむ水の音", yomi="ふるいけやかわずとびこむみずのおと")
    assert report.total_mora == 17


def test_segmented_yomi_wins_over_estimated_reading():
    # 「初むる」を形態素解析は「はつむる」と誤読する。節ごとの読みを与えれば
    # そちらが優先され、正しく定型と判定される。
    report = _analyze(
        "万緑の 中や吾子の歯 生え初むる",
        yomi="ばんりょくの なかやあこのは はえそむる",
    )
    assert report.split_source == "user"
    assert report.pattern == "5・7・5"
    assert report.is_teikei


def test_unsegmented_yomi_with_segmented_text_warns():
    report = _analyze(
        "万緑の 中や吾子の歯 生え初むる",
        yomi="ばんりょくのなかやあこのははえそむる",
    )
    assert report.split_source == "user-total"
    assert report.total_mora == 17
    assert any("区切って" in w for w in report.warnings)
