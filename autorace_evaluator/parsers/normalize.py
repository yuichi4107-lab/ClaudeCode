"""autorace.jp のセル文字列を正規化する純関数群。

すべて None 安全(None を渡すとエラーにせず None/デフォルト値を返す)。
result_parser.py はここの関数を経由してのみ DOM テキストを値に変換する。
"""

import re
import unicodedata

from . import selectors

# 数値(整数)を先頭から抜き出す正規表現。ハンデ欄の "10m" 等から使う。
_INT_RE = re.compile(r"-?\d+")

# 数値(小数可)を先頭から抜き出す正規表現。気温欄の "32.5°C" 等から使う。
_FLOAT_RE = re.compile(r"-?\d+(?:\.\d+)?")

# 空白文字(半角・全角とも)を除去するための正規表現。
_WHITESPACE_RE = re.compile(r"\s+")


def zen_to_han(s: str | None) -> str | None:
    """全角数字・英字・記号(．－ｍ等)を半角化し、空白を除去する。

    Unicode NFKC 正規化を使う(全角ASCII範囲の文字を機械的に半角化できる)。
    None はそのまま None を返す。
    """
    if s is None:
        return None
    if not isinstance(s, str):
        s = str(s)
    t = unicodedata.normalize("NFKC", s)
    t = _WHITESPACE_RE.sub("", t)
    return t


def parse_float(s: str | None) -> float | None:
    """"3.31" -> 3.31。"−" や空文字・None は None。"""
    t = zen_to_han(s)
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_handicap(s: str | None) -> int | None:
    """"0m" / "10ｍ" / "0" -> int。None安全。"""
    t = zen_to_han(s)
    if not t:
        return None
    m = _INT_RE.search(t)
    if not m:
        return None
    return int(m.group())


def parse_trial_time(s: str | None) -> tuple[float | None, int]:
    """試走タイム欄をパースする。

    selectors.RETRIAL_MARKS のいずれかを含めば (value, is_retrial=1)。
    "欠" 等の非数値は (None, 0)。返り値は (value, is_retrial)。
    """
    t = zen_to_han(s)
    if not t:
        return (None, 0)
    is_retrial = 1 if any(mark in t for mark in selectors.RETRIAL_MARKS) else 0
    cleaned = t
    for mark in selectors.RETRIAL_MARKS:
        cleaned = cleaned.replace(mark, "")
    value = parse_float(cleaned)
    return (value, is_retrial)


def parse_st(s: str | None) -> tuple[float | None, int]:
    """ST(スタートタイミング)欄をパースする。

    selectors.ST_FLYING_MARKS -> (None, is_flying=1)。
    selectors.ST_MISSING_MARKS -> (None, 0)。
    "0.12" -> (0.12, 0)。
    """
    t = zen_to_han(s)
    if t is None:
        t = ""
    if t in selectors.ST_FLYING_MARKS:
        return (None, 1)
    if t in selectors.ST_MISSING_MARKS:
        return (None, 0)
    return (parse_float(t), 0)


def parse_finish(s: str | None) -> tuple[int | None, str, str | None]:
    """着順欄をパースする。

    "1" -> (1, "finished", None)。
    selectors.ABNORMAL_STATUS_MAP に部分一致 -> (None, status, 原文)。
    判別不能 -> (None, "dnf", 原文)。
    返り値は (finish_pos, status, violation_note)。
    """
    original = s.strip() if isinstance(s, str) else s
    t = zen_to_han(s)
    if not t:
        return (None, "dnf", original)
    if t.isdigit():
        return (int(t), "finished", None)
    for mark, status in selectors.ABNORMAL_STATUS_MAP.items():
        if mark in t:
            return (None, status, original)
    return (None, "dnf", original)


def parse_track_status(s: str | None) -> str | None:
    """走路状態を selectors.TRACK_STATUS_MAP で正規化する。不明は None。"""
    t = zen_to_han(s)
    if not t:
        return None
    for key, normalized in selectors.TRACK_STATUS_MAP.items():
        if key in t:
            return normalized
    return None


def parse_temperature(s: str | None) -> float | None:
    """"32.5℃" -> 32.5。"""
    t = zen_to_han(s)
    if not t:
        return None
    m = _FLOAT_RE.search(t)
    if not m:
        return None
    return float(m.group())
