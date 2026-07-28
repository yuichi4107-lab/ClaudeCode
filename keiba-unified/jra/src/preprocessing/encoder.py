"""カテゴリ変数エンコーディングモジュール

カテゴリカルデータを数値に変換する。
"""

from typing import Optional

import pandas as pd

from src.utils.constants import (
    VENUE_NAME_TO_CODE,
    TRACK_CONDITION_CODES,
    SEX_CODES,
    GRADE_MAPPING,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def encode_venue(venue_name: str) -> Optional[int]:
    """競馬場名をコード番号に変換する"""
    if not venue_name:
        return None
    code = VENUE_NAME_TO_CODE.get(venue_name)
    return int(code) if code else None


def encode_track_condition(condition: str) -> Optional[int]:
    """馬場状態をコードに変換する"""
    if not condition:
        return None
    return TRACK_CONDITION_CODES.get(condition)


def encode_sex(sex_str: str) -> Optional[int]:
    """性別をコードに変換する"""
    if not sex_str:
        return None
    return SEX_CODES.get(sex_str)


def encode_grade(grade_str: str) -> Optional[int]:
    """グレードをコードに変換する"""
    if not grade_str:
        return None
    return GRADE_MAPPING.get(grade_str)


def encode_features(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrameの全カテゴリカル変数をエンコードする

    入力DataFrameのカラム名に応じて自動的にエンコーディングを適用する。
    """
    df = df.copy()

    if "venue_name" in df.columns:
        df["venue_code_num"] = df["venue_name"].apply(encode_venue)

    if "track_condition" in df.columns:
        df["track_condition_code"] = df["track_condition"].apply(
            encode_track_condition
        )

    if "sex" in df.columns:
        df["sex_code"] = df["sex"].apply(encode_sex)

    if "grade" in df.columns:
        df["grade_code"] = df["grade"].apply(encode_grade)

    logger.info("Encoded features: %d rows x %d cols", len(df), len(df.columns))
    return df
