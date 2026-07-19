"""autorace.jp API のフィールド値を正規化する純関数群。

すべて None 安全(None を渡すとエラーにせず None/デフォルト値を返す)。
result_parser.py はここの関数を経由してのみ API の値を変換する。
"""

import re
import unicodedata

from . import selectors

# 数値(整数)を先頭から抜き出す正規表現。ハンデ欄の "10m" 等から使う。
_INT_RE = re.compile(r"-?\d+")

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


def parse_float(s) -> float | None:
    """"3.31" / 3.31 -> 3.31。"−" や空文字・None は None。"""
    if isinstance(s, (int, float)):
        return float(s)
    t = zen_to_han(s)
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_int(s) -> int | None:
    """"10" / "10m" / 10 -> int。None安全。"""
    if isinstance(s, bool):
        return None
    if isinstance(s, int):
        return s
    if isinstance(s, float):
        return int(s)
    t = zen_to_han(s)
    if not t:
        return None
    m = _INT_RE.search(t)
    if not m:
        return None
    return int(m.group())


def track_status_from_code(code) -> str | None:
    """走路状況コード(situationCode)を正規化ラベルに変換する。不明は None。"""
    c = parse_int(code)
    if c is None:
        return None
    return selectors.SITUATION_TRACK_MAP.get(c)


def finish_from_api(order, accident_name) -> tuple[int | None, str, str | None]:
    """API の order / accidentName から (finish_pos, status, violation_note) を返す。

    - order が 1..8 なら finished(事故名があっても「故障完走」等は完走扱いで
      accidentName を violation_note に残す)。
    - order が無い/9以上なら accidentName を ACCIDENT_STATUS_MAP で status に解決。
    - どちらも無ければ (None, "dnf", None)。
    """
    pos = parse_int(order)
    name = accident_name if isinstance(accident_name, str) and accident_name.strip() else None

    if pos is not None and 1 <= pos <= 8:
        return (pos, "finished", name)

    if name:
        t = zen_to_han(name) or ""
        for mark, status in selectors.ACCIDENT_STATUS_MAP.items():
            if mark in t:
                return (None, status, name)
        return (None, "dnf", name)

    return (None, "dnf", None)


def st_from_api(st, foul_code) -> tuple[float | None, int]:
    """API の st / foulCode から (st, is_flying) を返す。

    foulCode "F" はフライング。ST値自体は掲載されていれば保持する。
    """
    is_flying = 0
    if isinstance(foul_code, str) and zen_to_han(foul_code) in [
        zen_to_han(c) for c in selectors.FOUL_FLYING_CODES
    ]:
        is_flying = 1
    return (parse_float(st), is_flying)


def trial_from_api(trial_time, retry_code) -> tuple[float | None, int]:
    """API の traialTime / traialRetryCode から (trial_time, is_retrial) を返す。"""
    is_retrial = 1 if parse_int(retry_code) in selectors.RETRIAL_CODES else 0
    return (parse_float(trial_time), is_retrial)


def foul_note(foul_code) -> str | None:
    """foulCode を可読ラベルに変換する。未知コードは原文のまま返す。"""
    if foul_code is None:
        return None
    t = zen_to_han(str(foul_code))
    if not t:
        return None
    return selectors.FOUL_NOTE_MAP.get(t, t)
