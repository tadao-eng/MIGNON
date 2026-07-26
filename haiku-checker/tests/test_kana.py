from haiku_checker import kana


def test_basic_mora_count():
    assert kana.count_mora("ふるいけや") == 5
    assert kana.count_mora("かわずとびこむ") == 7
    assert kana.count_mora("みずのおと") == 5


def test_youon_not_counted():
    # 「きょう」は 2 音（きょ／う）
    assert kana.count_mora("きょう") == 2
    assert kana.count_mora("しゃぼんだま") == 5


def test_sokuon_hatsuon_choon_counted():
    assert kana.count_mora("がっこう") == 4   # が・っ・こ・う
    assert kana.count_mora("ほん") == 2       # ほ・ん
    assert kana.count_mora("らーめん") == 4   # ら・ー・め・ん


def test_katakana_and_symbols():
    assert kana.count_mora("ラムネ") == 3
    assert kana.count_mora("みずのおと。") == 5
    assert kana.count_mora("ふるいけや かわず") == 8


def test_to_hiragana():
    assert kana.to_hiragana("カワズ") == "かわず"
    assert kana.to_hiragana("ラーメン") == "らーめん"


def test_kana_only_strips_kanji():
    assert kana.kana_only("古池やかわず") == "やかわず"


def test_mora_list_groups_youon():
    assert kana.mora_list("きょうしつ") == ["きょ", "う", "し", "つ"]


def test_separator_handling():
    assert kana.has_explicit_separator("古池や 蛙飛びこむ 水の音")
    assert kana.split_on_separators("古池や 蛙飛びこむ 水の音") == [
        "古池や", "蛙飛びこむ", "水の音"
    ]
