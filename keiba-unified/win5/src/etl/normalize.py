"""jra DBの表記を win5 の語彙へ正規化する純粋関数群"""

from config.venues import VENUE_NAME_TO_CODE, RACE_CLASS, SURFACE_TYPES

# jra の class 表記 → win5 RACE_CLASS のキー
CLASS_ALIASES = {
    "1勝": "1勝クラス",
    "2勝": "2勝クラス",
    "3勝": "3勝クラス",
    "OP": "オープン",
}


def normalize_class(jra_class: str) -> tuple[str, int]:
    """jra の class 文字列 → (win5クラス名, クラスコード)"""
    name = CLASS_ALIASES.get((jra_class or "").strip(), (jra_class or "").strip())
    return name, RACE_CLASS.get(name, 0)


def split_sex_age(sex_age: str) -> tuple[str, int]:
    """'牝3' → ('牝', 3)。空なら ('', 0)"""
    s = (sex_age or "").strip()
    if not s:
        return "", 0
    sex = s[0]
    digits = "".join(ch for ch in s[1:] if ch.isdigit())
    return sex, int(digits) if digits else 0


def normalize_surface(surface: str) -> str:
    """'ダート'→'dirt', '芝'→'turf'。未知は ''"""
    return SURFACE_TYPES.get((surface or "").strip(), "")


def venue_code_from_race_id(race_id: str) -> str:
    """netkeiba 12桁レースIDの会場コード2桁を返す（例: '2026 06 ...' → '06'）"""
    return race_id[4:6] if race_id and len(race_id) >= 6 else ""


def venue_name_to_code(venue_name: str) -> str:
    """会場名 → コード。未知は ''"""
    return VENUE_NAME_TO_CODE.get((venue_name or "").strip(), "")
