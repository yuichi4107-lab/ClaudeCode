"""データクリーニングモジュール

スクレイピングしたデータの前処理・型変換・欠損値処理を行う。
"""

import re
from typing import Optional, Tuple

import pandas as pd
import numpy as np

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def parse_time_to_seconds(time_str: str) -> Optional[float]:
    """タイム文字列を秒数に変換する

    Args:
        time_str: 'M:SS.s' or 'SS.s' format (e.g., '1:35.2' -> 95.2)

    Returns:
        float seconds, or None if unparseable
    """
    if not time_str or not isinstance(time_str, str):
        return None
    time_str = time_str.strip()
    if not time_str:
        return None
    match = re.match(r"(\d+):(\d+)\.(\d+)", time_str)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        frac = int(match.group(3))
        return minutes * 60.0 + seconds + frac * 0.1
    match = re.match(r"(\d+\.\d+)", time_str)
    if match:
        return float(match.group(1))
    return None


def parse_horse_weight(weight_str: str) -> Tuple[Optional[int], Optional[int]]:
    """馬体重文字列をパースする

    Args:
        weight_str: e.g., '480(+4)' or '480(-2)' or '480'

    Returns:
        (weight, change) tuple
    """
    if not weight_str or not isinstance(weight_str, str):
        return None, None
    weight_str = weight_str.strip()
    if not weight_str:
        return None, None
    match = re.match(r"(\d+)\(([+-]?\d+)\)", weight_str)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.match(r"(\d+)", weight_str)
    if match:
        return int(match.group(1)), None
    return None, None


def clean_race_data(df: pd.DataFrame) -> pd.DataFrame:
    """レース情報DataFrameをクリーニングする"""
    df = df.copy()

    # 文字列カラムのstrip
    str_cols = [
        "race_id", "venue_code", "venue_name", "race_name",
        "grade", "race_type", "direction", "track_condition", "weather",
    ]
    for col in str_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].replace({"None": None, "nan": None, "": None})

    # 日付型変換
    if "race_date" in df.columns:
        df["race_date"] = pd.to_datetime(df["race_date"], errors="coerce")

    # 数値型変換
    int_cols = ["kai", "nichi", "race_number", "distance", "horse_count", "prize_1st"]
    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    logger.info("Cleaned race data: %d rows", len(df))
    return df


def clean_results_data(df: pd.DataFrame) -> pd.DataFrame:
    """レース結果DataFrameをクリーニングする"""
    df = df.copy()

    # 文字列カラムのstrip
    str_cols = [
        "race_id", "horse_id", "horse_name", "sex_age",
        "jockey_id", "jockey_name", "trainer_id", "trainer_name",
        "margin", "corner_positions",
    ]
    for col in str_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].replace({"None": None, "nan": None, "": None})

    # 数値型変換
    int_cols = [
        "finish_order", "frame_number", "horse_number",
        "horse_weight", "weight_change", "popularity",
    ]
    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    float_cols = ["weight_carry", "finish_time", "final_3f", "odds"]
    for col in float_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 性別と年齢の分離
    if "sex_age" in df.columns:
        df["sex"] = df["sex_age"].str.extract(r"^(牡|牝|セ)")
        df["age"] = pd.to_numeric(
            df["sex_age"].str.extract(r"(\d+)$")[0], errors="coerce"
        ).astype("Int64")

    # 無効行の除去 (horse_numberがないもの)
    if "horse_number" in df.columns:
        before = len(df)
        df = df.dropna(subset=["horse_number"])
        dropped = before - len(df)
        if dropped > 0:
            logger.info("Dropped %d rows with missing horse_number", dropped)

    logger.info("Cleaned results data: %d rows", len(df))
    return df
