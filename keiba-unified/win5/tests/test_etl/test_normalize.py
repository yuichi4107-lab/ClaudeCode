from etl.normalize import (
    normalize_class,
    split_sex_age,
    normalize_surface,
    venue_code_from_race_id,
)


def test_normalize_class_aliases():
    assert normalize_class("1勝") == ("1勝クラス", 3)
    assert normalize_class("2勝") == ("2勝クラス", 4)
    assert normalize_class("3勝") == ("3勝クラス", 5)
    assert normalize_class("OP") == ("オープン", 6)
    assert normalize_class("G1") == ("G1", 10)
    assert normalize_class("未勝利") == ("未勝利", 2)
    assert normalize_class("新馬") == ("新馬", 1)
    assert normalize_class("") == ("", 0)


def test_split_sex_age():
    assert split_sex_age("牝3") == ("牝", 3)
    assert split_sex_age("牡5") == ("牡", 5)
    assert split_sex_age("セ7") == ("セ", 7)
    assert split_sex_age("") == ("", 0)


def test_normalize_surface():
    assert normalize_surface("ダート") == "dirt"
    assert normalize_surface("芝") == "turf"
    assert normalize_surface("") == ""


def test_venue_code_from_race_id():
    assert venue_code_from_race_id("202606030101") == "06"
    assert venue_code_from_race_id("") == ""
