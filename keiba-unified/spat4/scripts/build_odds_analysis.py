#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPAT4 トリプル馬単 オッズ推定・拡張CSV・分析ツール
人気順位から単勝オッズを推定し、拡張CSVを作成、オッズ帯別分析を実行する
"""

import csv
import os
from collections import defaultdict

# ==============================================================
# Step 1: 人気順位→推定単勝オッズの対応テーブル
# ==============================================================
# 根拠:
# - インサイダーオッズ最前線 (insider-odds.com) 人気別勝率・回収率データ
# - うまめし.com 地方競馬 人気別勝率データ
# - 競馬エンジニアのブログ オッズ別勝率データ
#
# JRA中央競馬の人気別平均オッズ (参考):
#   1番人気: 勝率32%, 単勝回収76 → 平均オッズ ≒ 76/32 ≒ 2.4倍
#   2番人気: 勝率19%, 単勝回収79 → 平均オッズ ≒ 79/19 ≒ 4.2倍
#   3番人気: 勝率14%, 単勝回収82 → 平均オッズ ≒ 82/14 ≒ 5.9倍
#   4番人気: 勝率9%,  単勝回収80 → 平均オッズ ≒ 80/9  ≒ 8.9倍
#   5番人気: 勝率7%,  単勝回収82 → 平均オッズ ≒ 82/7  ≒ 11.7倍
#   ...
#
# 地方競馬（南関東）は中央より1番人気の勝率が高い（大井31.9%, 船橋37.2%, 川崎35.7%）
# → 地方競馬の1番人気オッズは中央よりやや低め（人気が集中しやすい）
# → 推定テーブルは地方競馬向けに調整

# 人気順 → 推定単勝オッズ（地方競馬・南関東ベース）
POPULARITY_TO_ODDS = {
    1:  2.3,   # 地方1番人気: 勝率35%前後, 回収率75前後 → 75/35≒2.1, やや高めに2.3
    2:  4.0,   # 地方2番人気: 勝率19%前後, 回収率78前後 → 78/19≒4.1
    3:  6.5,   # 地方3番人気: 勝率13%前後, 回収率80前後 → 80/13≒6.2
    4:  9.5,   # 地方4番人気: 勝率9%前後,  回収率78前後 → 78/9≒8.7
    5:  13.0,  # 地方5番人気: 勝率7%前後,  回収率80前後 → 80/7≒11.4
    6:  18.0,  # 地方6番人気: 勝率5%前後
    7:  25.0,  # 地方7番人気: 勝率4%前後
    8:  35.0,  # 地方8番人気: 勝率3%前後
    9:  50.0,  # 地方9番人気: 勝率2%前後
    10: 70.0,  # 地方10番人気: 勝率1.5%前後
    11: 95.0,
    12: 130.0,
    13: 170.0,
    14: 220.0,
    15: 280.0,
    16: 350.0,
}

# 競馬場別の1番人気オッズ調整係数
# 地方競馬場ごとの1番人気勝率に基づく:
# 大井: 31.9% (フルゲート16頭、多頭数で荒れやすい) → やや高オッズ
# 船橋: 37.2% (フルゲート14頭) → 標準
# 川崎: 35.7% (フルゲート14頭) → 標準
# 浦和: 約36% (フルゲート12頭、小回り・少頭数) → やや低オッズ
# 門別: 約40% (フルゲート14頭、差しが効きにくく堅い) → 低オッズ
TRACK_FACTOR = {
    "大井": 1.10,   # 多頭数で荒れやすい → オッズやや高め
    "船橋": 1.00,   # 基準
    "川崎": 1.00,   # 基準
    "浦和": 0.90,   # 少頭数で堅め → オッズやや低め
    "門別": 0.85,   # 堅い傾向 → オッズ低め
}


def get_estimated_odds(popularity, track=None):
    """人気順位から推定単勝オッズを返す"""
    pop = int(popularity) if popularity else None
    if pop is None or pop < 1:
        return None
    if pop > 16:
        pop = 16
    base_odds = POPULARITY_TO_ODDS.get(pop, POPULARITY_TO_ODDS[16])
    if track and track in TRACK_FACTOR:
        return round(base_odds * TRACK_FACTOR[track], 1)
    return base_odds


def get_fav1_estimated_odds(pop_sum, track=None):
    """
    人気合計から1番人気のオッズ水準を推定する。
    人気合計が低い = 堅いレースが多い = 1番人気のオッズも低め
    人気合計が高い = 荒れたレースが含まれる = 1番人気のオッズは高め
    """
    if pop_sum is None:
        return None
    # 人気合計は3レース×2着(1着人気+2着人気)の合計
    # 最小=6(全レース1-1), 標準=18前後, 最大=60+
    # 人気合計/6 = 1レースあたりの平均(1着人気+2着人気)
    avg_per_race = pop_sum / 6.0

    # 1レースあたり平均が2 (=1番人気+1番人気) → 超堅い → 1番人気オッズ1.5前後
    # 1レースあたり平均が3 → 堅い → 1番人気オッズ2.0前後
    # 1レースあたり平均が4 → 標準 → 1番人気オッズ2.5前後
    # 1レースあたり平均が5以上 → 荒れ気味 → 1番人気オッズ3.0以上
    if avg_per_race <= 2.0:
        base = 1.5
    elif avg_per_race <= 2.5:
        base = 1.8
    elif avg_per_race <= 3.0:
        base = 2.1
    elif avg_per_race <= 3.5:
        base = 2.4
    elif avg_per_race <= 4.0:
        base = 2.7
    elif avg_per_race <= 5.0:
        base = 3.0
    else:
        base = 3.5

    if track and track in TRACK_FACTOR:
        return round(base * TRACK_FACTOR[track], 1)
    return base


# ==============================================================
# Step 2: CSV読み込み・拡張CSV作成
# ==============================================================

INPUT_CSV = r"D:\SPAT4\spat4.csv"
OUTPUT_CSV = r"D:\SPAT4\spat4_enhanced.csv"
TEMPLATE_CSV = r"D:\SPAT4\template_with_odds.csv"
ANALYSIS_MD = r"D:\SPAT4\analysis_odds.md"

# CSVを読み込む
rows = []
header = None
with open(INPUT_CSV, "r", encoding="utf-8-sig") as f:
    reader = csv.reader(f)
    for i, row in enumerate(reader):
        if i == 0:
            header = row
        else:
            # 空行をスキップ
            if not row or not row[0] or row[0].strip() == "":
                continue
            rows.append(row)

print(f"ヘッダー: {header}")
print(f"データ行数: {len(rows)}")

# ヘッダー構造確認
# 0:No, 1:フラグ, 2:日時, 3:競馬場, 4:開催日, 5:人気合計, 6:フラグ,
# 7:レース, 8:1着人気, 9:2着人気,
# 10:レース, 11:1着人気, 12:2着人気,
# 13:レース, 14:1着人気, 15:2着人気,
# 16:キャリーオーバー発声中, 17:的中口数, 18:的中金額, 19:キャリーオーバー

# 拡張ヘッダー
enhanced_header = header + [
    "推定1着オッズ_R1", "推定2着オッズ_R1",
    "推定1着オッズ_R2", "推定2着オッズ_R2",
    "推定1着オッズ_R3", "推定2着オッズ_R3",
    "推定1番人気オッズ_R1", "推定1番人気オッズ_R2", "推定1番人気オッズ_R3",
]

enhanced_rows = []
analysis_data = []  # 分析用データ

for row in rows:
    try:
        no_val = row[0].strip()
        track = row[3].strip() if len(row) > 3 else ""
        pop_sum_str = row[5].strip() if len(row) > 5 else ""
        flag = row[6].strip() if len(row) > 6 else ""

        pop_sum = int(pop_sum_str) if pop_sum_str else None

        # レース1: col 7(レース名), 8(1着人気), 9(2着人気)
        r1_name = row[7].strip() if len(row) > 7 else ""
        r1_win_pop_str = row[8].strip() if len(row) > 8 else ""
        r1_place_pop_str = row[9].strip() if len(row) > 9 else ""

        # レース2: col 10(レース名), 11(1着人気), 12(2着人気)
        r2_name = row[10].strip() if len(row) > 10 else ""
        r2_win_pop_str = row[11].strip() if len(row) > 11 else ""
        r2_place_pop_str = row[12].strip() if len(row) > 12 else ""

        # レース3: col 13(レース名), 14(1着人気), 15(2着人気)
        r3_name = row[13].strip() if len(row) > 13 else ""
        r3_win_pop_str = row[14].strip() if len(row) > 14 else ""
        r3_place_pop_str = row[15].strip() if len(row) > 15 else ""

        # 「同着」を含むレース名を処理
        r1_win_pop_str = r1_win_pop_str.replace("同着", "")
        r2_win_pop_str = r2_win_pop_str.replace("同着", "")
        r3_win_pop_str = r3_win_pop_str.replace("同着", "")

        # 人気を数値に変換
        def safe_int(s):
            try:
                return int(s)
            except (ValueError, TypeError):
                return None

        r1_win_pop = safe_int(r1_win_pop_str)
        r1_place_pop = safe_int(r1_place_pop_str)
        r2_win_pop = safe_int(r2_win_pop_str)
        r2_place_pop = safe_int(r2_place_pop_str)
        r3_win_pop = safe_int(r3_win_pop_str)
        r3_place_pop = safe_int(r3_place_pop_str)

        # 推定オッズ算出
        r1_win_odds = get_estimated_odds(r1_win_pop, track) if r1_win_pop else ""
        r1_place_odds = get_estimated_odds(r1_place_pop, track) if r1_place_pop else ""
        r2_win_odds = get_estimated_odds(r2_win_pop, track) if r2_win_pop else ""
        r2_place_odds = get_estimated_odds(r2_place_pop, track) if r2_place_pop else ""
        r3_win_odds = get_estimated_odds(r3_win_pop, track) if r3_win_pop else ""
        r3_place_odds = get_estimated_odds(r3_place_pop, track) if r3_place_pop else ""

        # 各レースの1番人気推定オッズ（人気合計とトラックから推定）
        fav1_odds_r1 = get_fav1_estimated_odds(pop_sum, track) if pop_sum else ""
        fav1_odds_r2 = get_fav1_estimated_odds(pop_sum, track) if pop_sum else ""
        fav1_odds_r3 = get_fav1_estimated_odds(pop_sum, track) if pop_sum else ""

        new_row = row + [
            r1_win_odds, r1_place_odds,
            r2_win_odds, r2_place_odds,
            r3_win_odds, r3_place_odds,
            fav1_odds_r1, fav1_odds_r2, fav1_odds_r3,
        ]
        enhanced_rows.append(new_row)

        # 分析用データ格納
        if pop_sum is not None:
            # 的中金額を解析
            prize_str = row[18].strip().replace(",", "").replace('"', '') if len(row) > 18 else ""
            prize = int(prize_str) if prize_str else 0

            # キャリーオーバー
            co_str = row[19].strip().replace(",", "").replace('"', '') if len(row) > 19 else ""
            co = int(co_str) if co_str else 0

            is_hit = prize > 0

            analysis_data.append({
                "no": no_val,
                "track": track,
                "pop_sum": pop_sum,
                "flag": flag,
                "r1_win_pop": r1_win_pop,
                "r1_place_pop": r1_place_pop,
                "r2_win_pop": r2_win_pop,
                "r2_place_pop": r2_place_pop,
                "r3_win_pop": r3_win_pop,
                "r3_place_pop": r3_place_pop,
                "r1_win_odds": r1_win_odds,
                "r2_win_odds": r2_win_odds,
                "r3_win_odds": r3_win_odds,
                "fav1_odds": fav1_odds_r1 if fav1_odds_r1 != "" else None,
                "prize": prize,
                "co": co,
                "is_hit": is_hit,
            })
    except Exception as e:
        print(f"Error processing row {row[:3]}: {e}")
        continue

# 拡張CSVを書き出す
with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(enhanced_header)
    for row in enhanced_rows:
        writer.writerow(row)

print(f"拡張CSV出力完了: {OUTPUT_CSV} ({len(enhanced_rows)}行)")


# ==============================================================
# Step 3: オッズ帯別分析
# ==============================================================

def classify_odds_tier(odds):
    """オッズを帯に分類"""
    if odds is None or odds == "":
        return None
    odds = float(odds)
    if odds < 2.0:
        return "1倍台"
    elif odds < 3.0:
        return "2倍台"
    else:
        return "3倍以上"


def classify_pop_sum_tier(ps):
    """人気合計を帯に分類"""
    if ps <= 12:
        return "~12(超堅)"
    elif ps <= 18:
        return "13~18(堅)"
    elif ps <= 24:
        return "19~24(中)"
    elif ps <= 30:
        return "25~30(荒)"
    else:
        return "31~(大荒)"


# ---- 分析1: 各レースの1着馬が1番人気だった場合の勝率（オッズ帯別） ----
# → 1番人気が1着に来たレース数 / 全レース数
fav1_win_by_odds_tier = defaultdict(lambda: {"total": 0, "win": 0})

for d in analysis_data:
    fav1_odds = d["fav1_odds"]
    if fav1_odds is None:
        continue
    tier = classify_odds_tier(fav1_odds)
    if tier is None:
        continue

    # 3レースそれぞれで1番人気が勝ったか確認
    for win_pop in [d["r1_win_pop"], d["r2_win_pop"], d["r3_win_pop"]]:
        if win_pop is not None:
            fav1_win_by_odds_tier[tier]["total"] += 1
            if win_pop == 1:
                fav1_win_by_odds_tier[tier]["win"] += 1

# ---- 分析2: 人気合計 × オッズ帯 クロス分析 ----
cross_analysis = defaultdict(lambda: {"total": 0, "hit": 0, "prize_sum": 0})

for d in analysis_data:
    fav1_odds = d["fav1_odds"]
    if fav1_odds is None:
        continue
    odds_tier = classify_odds_tier(fav1_odds)
    pop_tier = classify_pop_sum_tier(d["pop_sum"])
    key = f"{pop_tier} | {odds_tier}"
    cross_analysis[key]["total"] += 1
    if d["is_hit"]:
        cross_analysis[key]["hit"] += 1
        cross_analysis[key]["prize_sum"] += d["prize"]

# ---- 分析3: 競馬場 × オッズ帯 信頼度マトリクス ----
track_odds_matrix = defaultdict(lambda: {"total": 0, "win": 0})

for d in analysis_data:
    fav1_odds = d["fav1_odds"]
    if fav1_odds is None:
        continue
    tier = classify_odds_tier(fav1_odds)
    if tier is None:
        continue
    track = d["track"]

    for win_pop in [d["r1_win_pop"], d["r2_win_pop"], d["r3_win_pop"]]:
        if win_pop is not None:
            track_odds_matrix[(track, tier)]["total"] += 1
            if win_pop == 1:
                track_odds_matrix[(track, tier)]["win"] += 1

# ---- 追加分析: 推定オッズ帯別の的中率と平均配当 ----
# 1着馬の推定オッズ帯ごとに、トリプル馬単の的中傾向を分析
odds_tier_hit = defaultdict(lambda: {"total": 0, "hit": 0, "prize_sum": 0})
for d in analysis_data:
    # 最も低い1着オッズを取得（最も堅いレースの指標）
    win_odds_list = [d["r1_win_odds"], d["r2_win_odds"], d["r3_win_odds"]]
    valid_odds = [o for o in win_odds_list if o and o != ""]
    if not valid_odds:
        continue
    min_odds = min(valid_odds)
    max_odds = max(valid_odds)

    # 全1着馬の推定オッズの合計
    sum_odds = sum(float(o) for o in valid_odds)

    if sum_odds <= 10:
        tier = "合計~10(超堅)"
    elif sum_odds <= 20:
        tier = "合計11~20(堅)"
    elif sum_odds <= 40:
        tier = "合計21~40(中)"
    else:
        tier = "合計41~(荒)"

    odds_tier_hit[tier]["total"] += 1
    if d["is_hit"]:
        odds_tier_hit[tier]["hit"] += 1
        odds_tier_hit[tier]["prize_sum"] += d["prize"]

# ---- 追加分析: 人気合計別の1番人気勝率 ----
pop_sum_fav1_win = defaultdict(lambda: {"total_races": 0, "fav1_wins": 0})
for d in analysis_data:
    pop_tier = classify_pop_sum_tier(d["pop_sum"])
    for win_pop in [d["r1_win_pop"], d["r2_win_pop"], d["r3_win_pop"]]:
        if win_pop is not None:
            pop_sum_fav1_win[pop_tier]["total_races"] += 1
            if win_pop == 1:
                pop_sum_fav1_win[pop_tier]["fav1_wins"] += 1


# ==============================================================
# Step 4: 分析結果をMarkdownに出力
# ==============================================================

md_lines = []
md_lines.append("# SPAT4 トリプル馬単 推定オッズ分析レポート")
md_lines.append("")
md_lines.append("## 1. 人気順位→推定単勝オッズ対応テーブル")
md_lines.append("")
md_lines.append("地方競馬（南関東+門別）の実績データに基づく推定値。")
md_lines.append("インサイダーオッズ最前線、うまめし.com等の統計データを参考に、")
md_lines.append("人気別勝率と回収率から逆算して推定。")
md_lines.append("")
md_lines.append("| 人気順位 | 推定単勝オッズ | 参考勝率 | 根拠 |")
md_lines.append("|---------|-------------|---------|------|")
md_lines.append("| 1番人気 | 2.3倍 | 約35% | 地方1番人気勝率(大井31.9%/船橋37.2%/川崎35.7%) |")
md_lines.append("| 2番人気 | 4.0倍 | 約19% | 回収率78/勝率19≒4.1 |")
md_lines.append("| 3番人気 | 6.5倍 | 約13% | 回収率80/勝率13≒6.2 |")
md_lines.append("| 4番人気 | 9.5倍 | 約9% | 回収率78/勝率9≒8.7 |")
md_lines.append("| 5番人気 | 13.0倍 | 約7% | 回収率80/勝率7≒11.4 |")
md_lines.append("| 6番人気 | 18.0倍 | 約5% | |")
md_lines.append("| 7番人気 | 25.0倍 | 約4% | |")
md_lines.append("| 8番人気 | 35.0倍 | 約3% | |")
md_lines.append("| 9番人気 | 50.0倍 | 約2% | |")
md_lines.append("| 10番人気 | 70.0倍 | 約1.5% | |")
md_lines.append("| 11番人気以下 | 95~350倍 | 1%未満 | |")
md_lines.append("")

md_lines.append("### 競馬場別調整係数")
md_lines.append("")
md_lines.append("| 競馬場 | 調整係数 | 理由 |")
md_lines.append("|--------|---------|------|")
md_lines.append("| 大井 | ×1.10 | フルゲート16頭、多頭数で荒れやすい |")
md_lines.append("| 船橋 | ×1.00 | 基準 |")
md_lines.append("| 川崎 | ×1.00 | 基準 |")
md_lines.append("| 浦和 | ×0.90 | フルゲート12頭、少頭数で堅い |")
md_lines.append("| 門別 | ×0.85 | 差しが効きにくく逃げ先行有利、堅い傾向 |")
md_lines.append("")

md_lines.append("### 1番人気オッズ別信頼度（JRA参考値）")
md_lines.append("")
md_lines.append("| オッズ帯 | 勝率 | 連対率 | 複勝率 |")
md_lines.append("|---------|------|--------|--------|")
md_lines.append("| 1.0~1.4倍 | 62% | 81% | 89% |")
md_lines.append("| 1.5~1.9倍 | 45% | 66% | 78% |")
md_lines.append("| 2.0~2.9倍 | 31% | 52% | 65% |")
md_lines.append("| 3.0~3.9倍 | 23% | 40% | 54% |")
md_lines.append("| 4.0~4.9倍 | 17% | 31% | 42% |")
md_lines.append("| 5.0~6.9倍 | 16% | 29% | 38% |")
md_lines.append("")

# 分析1結果
md_lines.append("## 2. オッズ帯別 1番人気勝率分析")
md_lines.append("")
md_lines.append("推定された1番人気オッズ帯ごとに、実際に1番人気が1着になった割合を集計。")
md_lines.append("")
md_lines.append("| オッズ帯 | レース数 | 1番人気勝利数 | 1番人気勝率 |")
md_lines.append("|---------|---------|------------|-----------|")

for tier in ["1倍台", "2倍台", "3倍以上"]:
    data = fav1_win_by_odds_tier.get(tier, {"total": 0, "win": 0})
    total = data["total"]
    win = data["win"]
    rate = f"{win/total*100:.1f}%" if total > 0 else "-"
    md_lines.append(f"| {tier} | {total} | {win} | {rate} |")

md_lines.append("")

# 人気合計別1番人気勝率
md_lines.append("### 人気合計帯別 1番人気勝率")
md_lines.append("")
md_lines.append("| 人気合計帯 | レース数 | 1番人気勝利数 | 勝率 |")
md_lines.append("|-----------|---------|------------|------|")

for tier in ["~12(超堅)", "13~18(堅)", "19~24(中)", "25~30(荒)", "31~(大荒)"]:
    data = pop_sum_fav1_win.get(tier, {"total_races": 0, "fav1_wins": 0})
    total = data["total_races"]
    wins = data["fav1_wins"]
    rate = f"{wins/total*100:.1f}%" if total > 0 else "-"
    md_lines.append(f"| {tier} | {total} | {wins} | {rate} |")

md_lines.append("")

# 分析2結果
md_lines.append("## 3. 人気合計 × オッズ帯 クロス分析")
md_lines.append("")
md_lines.append("人気合計帯と推定1番人気オッズ帯の組み合わせ別に、トリプル馬単の的中率と平均配当を集計。")
md_lines.append("")
md_lines.append("| 人気合計帯 | オッズ帯 | 開催数 | 的中数 | 的中率 | 平均配当 |")
md_lines.append("|-----------|---------|-------|-------|--------|---------|")

# ソート用
pop_order = ["~12(超堅)", "13~18(堅)", "19~24(中)", "25~30(荒)", "31~(大荒)"]
odds_order = ["1倍台", "2倍台", "3倍以上"]

for pop_t in pop_order:
    for odds_t in odds_order:
        key = f"{pop_t} | {odds_t}"
        data = cross_analysis.get(key, {"total": 0, "hit": 0, "prize_sum": 0})
        total = data["total"]
        hit = data["hit"]
        rate = f"{hit/total*100:.1f}%" if total > 0 else "-"
        avg_prize = f"{data['prize_sum']//hit:,}円" if hit > 0 else "-"
        if total > 0:
            md_lines.append(f"| {pop_t} | {odds_t} | {total} | {hit} | {rate} | {avg_prize} |")

md_lines.append("")

# 分析3結果
md_lines.append("## 4. 競馬場 × オッズ帯 信頼度マトリクス")
md_lines.append("")
md_lines.append("競馬場ごと・推定1番人気オッズ帯ごとの1番人気勝率。")
md_lines.append("")

tracks = ["大井", "船橋", "川崎", "浦和", "門別"]
md_lines.append("| 競馬場 | 1倍台 | 2倍台 | 3倍以上 |")
md_lines.append("|--------|------|------|--------|")

for track in tracks:
    cells = [track]
    for tier in ["1倍台", "2倍台", "3倍以上"]:
        data = track_odds_matrix.get((track, tier), {"total": 0, "win": 0})
        if data["total"] > 0:
            rate = data["win"] / data["total"] * 100
            cells.append(f"{rate:.1f}% ({data['win']}/{data['total']})")
        else:
            cells.append("-")
    md_lines.append("| " + " | ".join(cells) + " |")

md_lines.append("")

# 推定オッズ合計帯別分析
md_lines.append("## 5. 3レース1着馬の推定オッズ合計帯別分析")
md_lines.append("")
md_lines.append("3レースの1着馬の推定単勝オッズを合計し、帯別にトリプル馬単の的中傾向を分析。")
md_lines.append("")
md_lines.append("| オッズ合計帯 | 開催数 | 的中数 | 的中率 | 平均配当 |")
md_lines.append("|------------|-------|-------|--------|---------|")

for tier in ["合計~10(超堅)", "合計11~20(堅)", "合計21~40(中)", "合計41~(荒)"]:
    data = odds_tier_hit.get(tier, {"total": 0, "hit": 0, "prize_sum": 0})
    total = data["total"]
    hit = data["hit"]
    rate = f"{hit/total*100:.1f}%" if total > 0 else "-"
    avg_prize = f"{data['prize_sum']//hit:,}円" if hit > 0 else "-"
    if total > 0:
        md_lines.append(f"| {tier} | {total} | {hit} | {rate} | {avg_prize} |")

md_lines.append("")

# 戦略的示唆
md_lines.append("## 6. 戦略的示唆")
md_lines.append("")
md_lines.append("### オッズ推定に基づく購入戦略の方向性")
md_lines.append("")

# データから自動的に戦略的示唆を生成
best_tier = None
best_rate = 0
for tier in ["1倍台", "2倍台", "3倍以上"]:
    data = fav1_win_by_odds_tier.get(tier, {"total": 0, "win": 0})
    if data["total"] > 0:
        rate = data["win"] / data["total"] * 100
        if rate > best_rate:
            best_rate = rate
            best_tier = tier

md_lines.append(f"1. **1番人気勝率が最も高いオッズ帯**: {best_tier}（勝率{best_rate:.1f}%）")
md_lines.append("   - この帯のレースが多い開催日は堅い決着が期待できる")
md_lines.append("")

# 競馬場別の最も信頼できるオッズ帯
md_lines.append("2. **競馬場別の1番人気信頼度**:")
for track in tracks:
    best_t = None
    best_r = 0
    for tier in ["1倍台", "2倍台", "3倍以上"]:
        data = track_odds_matrix.get((track, tier), {"total": 0, "win": 0})
        if data["total"] >= 10:
            rate = data["win"] / data["total"] * 100
            if rate > best_r:
                best_r = rate
                best_t = tier
    if best_t:
        md_lines.append(f"   - {track}: {best_t}帯で勝率{best_r:.1f}%")
md_lines.append("")

md_lines.append("3. **推定オッズの限界と改善策**:")
md_lines.append("   - 本推定はあくまで人気順位からの統計的推定であり、個別レースのオッズとは異なる")
md_lines.append("   - 実際のオッズデータを収集することで精度を大幅に向上できる")
md_lines.append("   - 特に1番人気のオッズ帯（1倍台/2倍台/3倍以上）の区別が重要")
md_lines.append("   - 今後はテンプレートCSVを使って実際のオッズを記録することを推奨")
md_lines.append("")

md_lines.append("## 7. 推定方法の詳細")
md_lines.append("")
md_lines.append("### 人気→オッズ変換の根拠")
md_lines.append("")
md_lines.append("平均オッズ = 単勝回収率 / 勝率 で推定。")
md_lines.append("例: 1番人気 → 回収率76 / 勝率32% = 2.375 ≒ 2.3倍（地方競馬は中央より堅いためやや低めに設定）")
md_lines.append("")
md_lines.append("### 1番人気推定オッズの算出")
md_lines.append("")
md_lines.append("人気合計（3レースの着順人気の合計値）からレースの「堅さ」を推定し、")
md_lines.append("1番人気のオッズ水準を逆推定。")
md_lines.append("- 人気合計6~12 → 1番人気オッズ1.5~1.8倍（非常に堅い）")
md_lines.append("- 人気合計13~18 → 1番人気オッズ2.0~2.4倍（やや堅い）")
md_lines.append("- 人気合計19~24 → 1番人気オッズ2.5~2.7倍（標準）")
md_lines.append("- 人気合計25~30 → 1番人気オッズ3.0倍前後（やや荒れ）")
md_lines.append("- 人気合計31以上 → 1番人気オッズ3.5倍以上（荒れ傾向）")
md_lines.append("")
md_lines.append("### データソース")
md_lines.append("")
md_lines.append("- [インサイダーオッズ最前線 - 単勝1番人気オッズ別勝率・回収率データ](https://www.insider-odds.com/data/304/)")
md_lines.append("- [インサイダーオッズ最前線 - 単勝人気別勝率・回収率データ](https://www.insider-odds.com/data/301/)")
md_lines.append("- [うまめし.com - 競馬 単勝 人気別 勝率 連対率 複勝率 中央地方データ](https://www.umameshi.com/)")
md_lines.append("- [競馬エンジニアのブログ - 単勝オッズ別勝率・連対率・複勝率](https://keiba-e.com/)")
md_lines.append("")

# 分析結果を書き出し
with open(ANALYSIS_MD, "w", encoding="utf-8") as f:
    f.write("\n".join(md_lines))

print(f"分析レポート出力完了: {ANALYSIS_MD}")


# ==============================================================
# Step 4: テンプレートCSV作成
# ==============================================================

template_header = [
    "No", "日時", "競馬場", "開催日",
    "レース1", "R1_1番人気単勝オッズ", "R1_2番人気単勝オッズ", "R1_出走頭数", "R1_1着人気", "R1_2着人気",
    "レース2", "R2_1番人気単勝オッズ", "R2_2番人気単勝オッズ", "R2_出走頭数", "R2_1着人気", "R2_2着人気",
    "レース3", "R3_1番人気単勝オッズ", "R3_2番人気単勝オッズ", "R3_出走頭数", "R3_1着人気", "R3_2着人気",
    "人気合計", "フラグ", "キャリーオーバー発声中",
    "的中口数", "的中金額", "キャリーオーバー", "メモ"
]

# サンプル行
template_sample = [
    "1", "3月1日(土)", "大井", "第20回1日目",
    "10R", "", "", "", "", "",
    "11R", "", "", "", "", "",
    "12R", "", "", "", "", "",
    "", "", "",
    "", "", "", ""
]

with open(TEMPLATE_CSV, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(template_header)
    writer.writerow(template_sample)

print(f"テンプレートCSV出力完了: {TEMPLATE_CSV}")

print("\n全処理完了!")
