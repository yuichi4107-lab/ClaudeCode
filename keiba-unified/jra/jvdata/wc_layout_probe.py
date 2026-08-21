"""
JRA-VAN WC (ウッドチップ調教) レコード 固定長レイアウト検証スクリプト
====================================================================

対象: C:\\Users\\fcmdt\\jvdata\\raw\\WOOD\\WC.txt (752,329行, 1行103バイト固定長, UTF-8)
方針: HC(坂路)で確立した手法と同じく、末尾から
      「Fkハロン累計 - lap(k→k-1) = F(k-1)ハロン累計(またはF1)」
      の恒等式が成り立つオフセットを総当たりで確認する。

このスクリプトは読み取り専用。WC.txt は一切変更しない。

確定レイアウト (103バイト固定長)
---------------------------------------------------------------
[0:2]    "WC"                     レコード種別ID
[2:3]    データ区分                観測値は常に "1"
[3:11]   データ作成年月日 YYYYMMDD
[11:12]  トレセン区分               "0"=栗東 / "1"=美浦 (下記コースコードと完全一致)
[12:20]  調教年月日 YYYYMMDD
[20:24]  調教時刻 HHMM
[24:34]  血統登録番号 (10桁)
[34:36]  コースコード (2桁)         "20"/"21"(トレセン区分=1で出現) , "30"/"31"(トレセン区分=0で出現)
[36:37]  予備/未使用                観測値は100%が"0"
[37:103] ハロンタイム系列 (66桁)    後述

ハロンタイム系列 [37:103] の内訳 (すべて 0.1秒単位、右詰め・0埋め)
  F10ハロン累計(4) lap10-9(3) F9累計(4) lap9-8(3) F8累計(4) lap8-7(3)
  F7累計(4) lap7-6(3) F6累計(4) lap6-5(3) F5累計(4) lap5-4(3)
  F4累計(4) lap4-3(3) F3累計(4) lap3-2(3) F2累計(4) lap2-1(3) F1(3)

  9組(cum4+lap3) × 7バイト = 63バイト + F1(3バイト) = 66バイト
  実際のウッドチップ調教は6F前後が主体のため、F7～F10側は0埋めのことが多い。
"""

from pathlib import Path
import collections
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

WC_PATH = Path(r"C:\Users\fcmdt\jvdata\raw\WOOD\WC.txt")

# ---- フィールドオフセット定義 -------------------------------------------

HEADER_FIELDS = [
    ("record_id",   0, 2),
    ("data_kubun",  2, 3),
    ("create_date", 3, 11),
    ("tresen_kubun", 11, 12),
    ("train_date",  12, 20),
    ("train_time",  20, 24),
    ("horse_id",    24, 34),
    ("course_code", 34, 36),
    ("reserved",    36, 37),
]


def build_furlong_fields():
    """[37:103] の66バイトを F10..F2 の (累計4桁, ラップ3桁) 反復 + F1(3桁) に分割"""
    pos = 37
    fields = []
    for k in range(10, 1, -1):
        fields.append((f"F{k}cum", pos, pos + 4))
        pos += 4
        fields.append((f"lap{k}_{k-1}", pos, pos + 3))
        pos += 3
    fields.append(("F1", pos, pos + 3))
    pos += 3
    assert pos == 103, f"unexpected end offset {pos}"
    return fields


FURLONG_FIELDS = build_furlong_fields()
ALL_FIELDS = HEADER_FIELDS + FURLONG_FIELDS


def parse_line(line: str) -> dict:
    """1行を dict にパースする。数値系フィールドは int (0.1秒単位) にする。"""
    line = line.rstrip("\n\r")
    rec = {}
    for name, s, e in HEADER_FIELDS:
        rec[name] = line[s:e]
    for name, s, e in FURLONG_FIELDS:
        rec[name] = int(line[s:e])
    return rec


# ---- 検証ロジック --------------------------------------------------------

def verify(path: Path, limit: int | None = None):
    total_lines = 0
    length_dist = collections.Counter()
    course_dist = collections.Counter()
    tresen_dist = collections.Counter()
    nonzero_counts = {k: 0 for k in [1, 2, 3, 4, 5, 6]}

    total_checks = 0
    mismatch_total = 0
    mismatch_sentinel = 0
    mismatch_gap = 0
    mismatch_other = 0
    bad_time = 0
    bad_date_order = 0

    with path.open(encoding="utf-8") as f:
        for i, raw in enumerate(f):
            if limit is not None and i >= limit:
                break
            line = raw.rstrip("\n\r")
            total_lines += 1
            length_dist[len(line)] += 1

            if len(line) != 103:
                continue  # skip malformed line lengths for detailed checks

            rec = parse_line(line)
            course_dist[rec["course_code"]] += 1
            tresen_dist[rec["tresen_kubun"]] += 1

            hhmm = rec["train_time"]
            if not (hhmm.isdigit() and 0 <= int(hhmm[:2]) <= 23 and 0 <= int(hhmm[2:]) <= 59):
                bad_time += 1
            if rec["train_date"].isdigit() and rec["create_date"].isdigit():
                if rec["train_date"] > rec["create_date"]:
                    bad_date_order += 1

            for k in [1, 2, 3, 4, 5, 6]:
                key = "F1" if k == 1 else f"F{k}cum"
                if rec[key] != 0:
                    nonzero_counts[k] += 1

            # 恒等式チェック: Fk_cum - lap(k,k-1) == F(k-1) (cum or F1)
            for k in range(10, 1, -1):
                cum_v = rec[f"F{k}cum"]
                lap_v = rec[f"lap{k}_{k-1}"]
                prev_v = rec["F1"] if k - 1 == 1 else rec[f"F{k-1}cum"]
                if cum_v != 0:
                    total_checks += 1
                    if cum_v - lap_v != prev_v:
                        mismatch_total += 1
                        if cum_v == 9999 or lap_v == 999:
                            mismatch_sentinel += 1
                        elif lap_v == 0 and prev_v == 0:
                            mismatch_gap += 1
                        else:
                            mismatch_other += 1

    return {
        "total_lines": total_lines,
        "length_dist": length_dist,
        "course_dist": course_dist,
        "tresen_dist": tresen_dist,
        "nonzero_counts": nonzero_counts,
        "total_checks": total_checks,
        "mismatch_total": mismatch_total,
        "mismatch_sentinel": mismatch_sentinel,
        "mismatch_gap": mismatch_gap,
        "mismatch_other": mismatch_other,
        "bad_time": bad_time,
        "bad_date_order": bad_date_order,
    }


def main():
    result = verify(WC_PATH)

    print("=== 行長分布 ===")
    for k, v in sorted(result["length_dist"].items()):
        print(f"  len={k}: {v}")

    print("\n=== ヘッダー整合性 ===")
    print(f"  total_lines = {result['total_lines']}")
    print(f"  train_time 不正 = {result['bad_time']}")
    print(f"  train_date > create_date = {result['bad_date_order']}")

    print("\n=== コースコード分布 [34:36] (トレセン区分[11:12]別) ===")
    for code, cnt in result["course_dist"].most_common():
        print(f"  {code}: {cnt}")
    print("  tresen_kubun[11:12] distribution:", dict(result["tresen_dist"]))

    print("\n=== 恒等式検証 (Fk_cum - lap(k,k-1) == F(k-1)) ===")
    tc = result["total_checks"]
    mm = result["mismatch_total"]
    print(f"  total_checks = {tc}")
    print(f"  mismatches   = {mm}  (rate = {mm/tc:.6f})")
    print(f"  match_rate   = {1 - mm/tc:.6f}")
    print(f"    うちセンチネル(9999/999) = {result['mismatch_sentinel']}")
    print(f"    うちデータ欠落(lap=0,prev=0) = {result['mismatch_gap']}")
    print(f"    うち原因不明 = {result['mismatch_other']}")

    print("\n=== 有効タイム非ゼロ率 (F6/F5/F4/F3/F1) ===")
    n = result["total_lines"]
    for k in [6, 5, 4, 3, 1]:
        c = result["nonzero_counts"][k]
        print(f"  F{k}: {c}/{n} = {c/n:.4%}")


if __name__ == "__main__":
    main()
