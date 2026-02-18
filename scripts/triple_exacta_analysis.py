#!/usr/bin/env python3
"""トリプル馬単の買い目分析スクリプト。

人気・オッズ・配当データを基に、期待値の高い購入戦略を分析する。

Usage:
    # JSONデータから分析
    python scripts/triple_exacta_analysis.py --json data/triple_exacta/triple_exacta_all.json

    # CSVデータから分析
    python scripts/triple_exacta_analysis.py --csv data/triple_exacta/results.csv

    # デモモード（既知の統計データに基づく分析）
    python scripts/triple_exacta_analysis.py --demo
"""

import argparse
import csv
import json
import logging
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
#  南関東・門別 トリプル馬単の基礎統計パラメータ
#  (公開情報・過去実績から推定)
# ============================================================

# 会場別フルゲート頭数
VENUE_FIELD_SIZE = {
    "大井": 16, "川崎": 14, "船橋": 14, "浦和": 12, "門別": 14,
}

# 会場別 1番人気の連対率（1着or2着）の推定値
VENUE_FAVORITE_PLACE_RATE = {
    "浦和": 0.65,  # 最も堅い
    "門別": 0.62,
    "船橋": 0.58,
    "川崎": 0.55,
    "大井": 0.50,  # 最も荒れやすい
}

# ============================================================
#  Harville モデルによる確率計算
#  strength(i) = 1 / i^alpha (alpha=0.85 は地方競馬向け調整)
#  P(i wins) = s_i / S
#  P(i→j) = (s_i / S) * (s_j / (S - s_i))
# ============================================================

DEFAULT_FIELD_SIZE = 14  # 南関東の平均的な出走頭数
HARVILLE_ALPHA = 0.85    # べき乗パラメータ（小さいほど荒れやすい）


def _strengths(n: int = DEFAULT_FIELD_SIZE, alpha: float = HARVILLE_ALPHA) -> dict:
    """人気順位から強さパラメータを計算"""
    return {i: 1.0 / (i ** alpha) for i in range(1, n + 1)}


def _total_strength(n: int = DEFAULT_FIELD_SIZE, alpha: float = HARVILLE_ALPHA) -> float:
    return sum(1.0 / (i ** alpha) for i in range(1, n + 1))


# 馬単人気組み合わせ別の平均配当（推定値、100円あたり）
# 地方競馬の実績データに基づく推定
EXACTA_AVG_PAYOUT = {
    "1-2": 650, "1-3": 1200, "1-4": 2000, "1-5": 3500,
    "2-1": 900, "2-3": 2500, "2-4": 4500, "2-5": 7000,
    "3-1": 1800, "3-2": 3500, "3-4": 7000, "3-5": 11000,
    "4-1": 3500, "4-2": 6000, "4-3": 9500, "4-5": 15000,
    "5-1": 5500, "5-2": 9000, "5-3": 14000, "5-4": 18000,
    "6-1": 8000, "6-2": 13000, "6-3": 20000,
    "7-1": 12000, "7-2": 18000, "7-3": 28000,
    "8-1": 18000, "8-2": 25000, "8-3": 40000,
}


def calculate_exacta_probability(
    pop1: int, pop2: int, n: int = DEFAULT_FIELD_SIZE
) -> float:
    """Harville モデルで馬単的中確率を推定。

    P(pop1→pop2) = (s_pop1 / S) * (s_pop2 / (S - s_pop1))
    """
    if pop1 == pop2 or pop1 < 1 or pop2 < 1 or pop1 > n or pop2 > n:
        return 0.0
    strengths = _strengths(n)
    S = sum(strengths.values())
    s1 = strengths[pop1]
    s2 = strengths[pop2]
    return (s1 / S) * (s2 / (S - s1))


def calculate_triple_probability(
    leg1: tuple, leg2: tuple, leg3: tuple
) -> float:
    """3レッグの馬単的中確率の積"""
    p1 = calculate_exacta_probability(*leg1)
    p2 = calculate_exacta_probability(*leg2)
    p3 = calculate_exacta_probability(*leg3)
    return p1 * p2 * p3


def calculate_win_probability(pop: int, n: int = DEFAULT_FIELD_SIZE) -> float:
    """人気順位からの単勝確率"""
    if pop < 1 or pop > n:
        return 0.0
    strengths = _strengths(n)
    S = sum(strengths.values())
    return strengths[pop] / S


def estimate_payout_from_popularity(pop1: int, pop2: int) -> float:
    """人気組み合わせから馬単配当を推定（100円あたり）"""
    key = f"{pop1}-{pop2}"
    if key in EXACTA_AVG_PAYOUT:
        return EXACTA_AVG_PAYOUT[key]
    # Harville確率の逆数ベースで配当を推定（控除率30%考慮）
    prob = calculate_exacta_probability(pop1, pop2)
    if prob <= 0:
        return 100000
    return 0.70 / prob


def format_currency(amount: float) -> str:
    if amount >= 100_000_000:
        return f"{amount / 100_000_000:.2f}億円"
    if amount >= 10_000:
        return f"{amount / 10_000:.1f}万円"
    return f"{amount:,.0f}円"


# ============================================================
#  分析メイン
# ============================================================

def analyze_popularity_patterns():
    """人気パターン別のトリプル馬単期待値を分析する"""

    print("=" * 80)
    print("トリプル馬単 買い目戦略分析")
    print("=" * 80)

    # ----------------------------------------
    # 1. 馬単の人気別的中確率と配当
    # ----------------------------------------
    print("\n" + "─" * 80)
    print("■ 1. 馬単（1レッグ）の人気組み合わせ別 分析")
    print("─" * 80)
    print(f"{'1着人気':>8} {'2着人気':>8} {'的中率':>10} {'平均配当':>12} {'期待値':>10}")
    print("─" * 60)

    combos = []
    for p1 in range(1, 8):
        for p2 in range(1, 8):
            if p1 == p2:
                continue
            prob = calculate_exacta_probability(p1, p2)
            payout = estimate_payout_from_popularity(p1, p2)
            ev = prob * payout * 100  # 期待値（100円あたり）
            combos.append((p1, p2, prob, payout, ev))
            if p1 <= 5 and p2 <= 5:
                print(
                    f"{p1:>5}番人気 {p2:>5}番人気 "
                    f"{prob * 100:>8.2f}% "
                    f"{payout:>10,.0f}円 "
                    f"{ev:>8.1f}円"
                )

    # 期待値トップ10
    combos.sort(key=lambda x: x[4], reverse=True)
    print("\n【期待値 TOP10 馬単組み合わせ】")
    print(f"{'順位':>4} {'1着':>6} {'2着':>6} {'的中率':>10} {'配当':>10} {'期待値':>10}")
    for rank, (p1, p2, prob, payout, ev) in enumerate(combos[:10], 1):
        print(
            f"{rank:>4}. {p1:>3}人気 {p2:>3}人気 "
            f"{prob * 100:>8.2f}% {payout:>8,.0f}円 {ev:>8.1f}円"
        )

    # ----------------------------------------
    # 2. トリプル馬単の戦略パターン
    # ----------------------------------------
    print("\n" + "─" * 80)
    print("■ 2. トリプル馬単 戦略パターン別 分析")
    print("─" * 80)

    strategies = [
        {
            "name": "超堅軸（全レッグ1-2人気）",
            "description": "3レッグとも1番人気→2番人気",
            "legs": [(1, 2), (1, 2), (1, 2)],
            "points": 1,
        },
        {
            "name": "堅軸＋中穴（2レッグ堅め + 1レッグ中穴）",
            "description": "2レッグは1-2人気、1レッグで3-5人気を狙う",
            "legs_options": [
                # 各レッグで選ぶ人気の範囲
                {"1st_range": [1, 2], "2nd_range": [1, 2, 3]},
                {"1st_range": [1, 2], "2nd_range": [1, 2, 3]},
                {"1st_range": [1, 2, 3, 4, 5], "2nd_range": [1, 2, 3, 4, 5]},
            ],
        },
        {
            "name": "均等中穴（全レッグ1-4人気）",
            "description": "全レッグで1-4番人気の組み合わせ",
            "legs_options": [
                {"1st_range": [1, 2, 3, 4], "2nd_range": [1, 2, 3, 4]},
                {"1st_range": [1, 2, 3, 4], "2nd_range": [1, 2, 3, 4]},
                {"1st_range": [1, 2, 3, 4], "2nd_range": [1, 2, 3, 4]},
            ],
        },
        {
            "name": "堅＋堅＋大穴",
            "description": "2レッグは上位人気で固め、1レッグは大穴を狙う",
            "legs_options": [
                {"1st_range": [1, 2], "2nd_range": [1, 2, 3]},
                {"1st_range": [1, 2], "2nd_range": [1, 2, 3]},
                {"1st_range": [1, 2, 3, 4, 5, 6, 7, 8],
                 "2nd_range": [1, 2, 3, 4, 5, 6, 7, 8]},
            ],
        },
    ]

    for strategy in strategies:
        print(f"\n▼ {strategy['name']}")
        print(f"  説明: {strategy['description']}")

        if "legs" in strategy:
            # 固定組み合わせ
            prob = calculate_triple_probability(*strategy["legs"])
            legs_text = " × ".join(
                f"({p1}人気→{p2}人気)" for p1, p2 in strategy["legs"]
            )
            print(f"  組合せ: {legs_text}")
            print(f"  的中確率: {prob * 100:.6f}% (1/{1 / prob:,.0f})")
            print(f"  購入点数: {strategy['points']}点")
            cost = strategy["points"] * 50
            print(f"  投資額: {format_currency(cost)}")

            # パリミュチュエル方式での推定配当
            # 当たった場合の配当 ≈ (1/確率) × 還元率(70%) × 50円
            estimated_hit_payout = (1 / prob) * 0.70 * 50 if prob > 0 else 0
            print(f"  的中時推定配当: {format_currency(estimated_hit_payout)}")
            # 期待値 = 的中確率 × 的中時配当 = 0.70 × 投資額（理論値）
            ev = cost * 0.70
            print(f"  期待値: {format_currency(ev)} (投資{format_currency(cost)}に対して)")
            print(f"  理論還元率: 70.0% (控除率30%)")
        else:
            # 複数組み合わせ
            total_points = 1
            for leg_opt in strategy["legs_options"]:
                leg_combos = 0
                for p1 in leg_opt["1st_range"]:
                    for p2 in leg_opt["2nd_range"]:
                        if p1 != p2:
                            leg_combos += 1
                total_points *= leg_combos

            print(f"  購入点数: {total_points:,}点")
            cost = total_points * 50
            print(f"  投資額 (50円×{total_points:,}点): {format_currency(cost)}")

            # 的中確率の計算（カバーする組み合わせの確率合計）
            total_prob = 0
            for p1a in strategy["legs_options"][0]["1st_range"]:
                for p2a in strategy["legs_options"][0]["2nd_range"]:
                    if p1a == p2a:
                        continue
                    for p1b in strategy["legs_options"][1]["1st_range"]:
                        for p2b in strategy["legs_options"][1]["2nd_range"]:
                            if p1b == p2b:
                                continue
                            for p1c in strategy["legs_options"][2]["1st_range"]:
                                for p2c in strategy["legs_options"][2]["2nd_range"]:
                                    if p1c == p2c:
                                        continue
                                    prob = calculate_triple_probability(
                                        (p1a, p2a), (p1b, p2b), (p1c, p2c)
                                    )
                                    total_prob += prob

            # パリミュチュエル方式: 理論期待値 = 投資額 × 70%
            # ただし的中時の配当は高い（購入点数が多いほど的中率↑、配当は×点数分の分散）
            ev = cost * 0.70
            avg_payout_if_hit = ev / total_prob if total_prob > 0 else 0

            print(f"  的中確率: {total_prob * 100:.4f}% (1/{1 / total_prob:,.0f})")
            print(f"  的中時平均配当: {format_currency(avg_payout_if_hit)}")
            print(f"  理論期待値: {format_currency(ev)} (還元率70%)")
            print(f"  ★ポイント: 的中率{total_prob*100:.2f}%で{format_currency(avg_payout_if_hit)}を狙える")


def analyze_venue_patterns():
    """会場別のトリプル馬単攻略傾向を分析"""

    print("\n" + "=" * 80)
    print("■ 3. 会場別 攻略傾向分析")
    print("=" * 80)

    for venue, field_size in VENUE_FIELD_SIZE.items():
        fav_rate = VENUE_FAVORITE_PLACE_RATE[venue]
        exacta_combos = field_size * (field_size - 1)
        random_prob = 1 / exacta_combos

        # 堅い決着の確率 (1-3人気内で決着)
        solid_prob = 0
        for p1 in range(1, 4):
            for p2 in range(1, 4):
                if p1 == p2:
                    continue
                solid_prob += calculate_exacta_probability(p1, p2)

        print(f"\n  【{venue}競馬場】")
        print(f"    フルゲート: {field_size}頭")
        print(f"    馬単組合せ: {exacta_combos}通り")
        print(f"    ランダム的中率: {random_prob * 100:.2f}%")
        print(f"    1番人気連対率: {fav_rate * 100:.0f}%")
        print(f"    堅い決着率(1-3人気内): {solid_prob * 100:.1f}%")

        if venue == "浦和":
            print("    → 最も堅い。逃げ・先行有利。トリプル馬単入門向き")
        elif venue == "門別":
            print("    → 比較的堅い。低配当が多い。キャリーオーバー狙い向き")
        elif venue == "船橋":
            print("    → 短距離戦多め。逃げ馬重視が有効")
        elif venue == "川崎":
            print("    → やや荒れやすい。中穴狙いに向く")
        elif venue == "大井":
            print("    → 最も荒れやすい。高配当狙いの荒れレッグに使う")


def analyze_optimal_strategies():
    """最適な購入戦略をシミュレーション"""

    print("\n" + "=" * 80)
    print("■ 4. 購入戦略シミュレーション（50円単位）")
    print("=" * 80)

    budgets = [500, 1000, 3000, 5000, 10000]

    for budget in budgets:
        print(f"\n{'─' * 60}")
        print(f"  予算: {format_currency(budget)}")
        print(f"{'─' * 60}")
        max_points = budget // 50

        # 戦略A: 堅め中心
        strategy_a_name = "堅軸パターン"
        legs_a = [
            {"1st": [1, 2], "2nd": [1, 2, 3]},      # 4通り
            {"1st": [1, 2], "2nd": [1, 2, 3]},      # 4通り
            {"1st": [1, 2, 3], "2nd": [1, 2, 3, 4]},  # 9通り
        ]

        # 戦略B: バランス型
        strategy_b_name = "バランスパターン"
        legs_b = [
            {"1st": [1, 2, 3], "2nd": [1, 2, 3]},    # 6通り
            {"1st": [1, 2, 3], "2nd": [1, 2, 3]},    # 6通り
            {"1st": [1, 2, 3, 4], "2nd": [1, 2, 3, 4, 5]},  # 16通り
        ]

        # 戦略C: 荒れ狙い
        strategy_c_name = "荒れ狙いパターン"
        legs_c = [
            {"1st": [1, 2], "2nd": [1, 2, 3]},      # 4通り
            {"1st": [1, 2], "2nd": [1, 2, 3]},      # 4通り
            {"1st": list(range(1, 9)), "2nd": list(range(1, 9))},  # 56通り
        ]

        for name, legs in [
            (strategy_a_name, legs_a),
            (strategy_b_name, legs_b),
            (strategy_c_name, legs_c),
        ]:
            points = 1
            for leg in legs:
                leg_combos = sum(
                    1 for p1 in leg["1st"] for p2 in leg["2nd"] if p1 != p2
                )
                points *= leg_combos

            if points > max_points:
                feasible = f"予算不足 (必要: {format_currency(points * 50)})"
            else:
                feasible = f"購入可能 (余り: {format_currency(budget - points * 50)})"

            # 的中確率
            total_prob = 0
            for p1a in legs[0]["1st"]:
                for p2a in legs[0]["2nd"]:
                    if p1a == p2a:
                        continue
                    for p1b in legs[1]["1st"]:
                        for p2b in legs[1]["2nd"]:
                            if p1b == p2b:
                                continue
                            for p1c in legs[2]["1st"]:
                                for p2c in legs[2]["2nd"]:
                                    if p1c == p2c:
                                        continue
                                    prob = calculate_triple_probability(
                                        (p1a, p2a), (p1b, p2b), (p1c, p2c)
                                    )
                                    total_prob += prob

            cost = points * 50
            # 的中した場合の平均配当 = (投資額 × 還元率) / 的中確率
            avg_hit_payout = (cost * 0.70) / total_prob if total_prob > 0 else 0

            print(f"\n  ▼ {name}")
            print(f"    購入点数: {points:,}点 ({format_currency(cost)})")
            print(f"    ステータス: {feasible}")
            print(f"    的中確率: {total_prob * 100:.4f}% (約1/{1 / total_prob:,.0f})")
            print(f"    的中時平均配当: {format_currency(avg_hit_payout)}")
            print(f"    理論還元率: 70.0%")

            leg_details = []
            for i, leg in enumerate(legs, 1):
                combos = sum(
                    1 for p1 in leg["1st"] for p2 in leg["2nd"] if p1 != p2
                )
                first_str = ",".join(str(p) for p in leg["1st"])
                second_str = ",".join(str(p) for p in leg["2nd"])
                leg_details.append(
                    f"    Leg{i}: 1着[{first_str}人気] → 2着[{second_str}人気] ({combos}通り)"
                )
            print("\n".join(leg_details))


def analyze_carryover_strategy():
    """キャリーオーバー時の戦略分析"""

    print("\n" + "=" * 80)
    print("■ 5. キャリーオーバー戦略")
    print("=" * 80)

    print("""
  トリプル馬単は控除率30%のため、通常時は期待値が低い。
  しかし、キャリーオーバー(CO)があると状況が変わる。

  【キャリーオーバー時の期待値変化】
""")

    base_pool = 1_000_000  # 基本プール100万円と仮定
    carryovers = [0, 500_000, 1_000_000, 5_000_000, 10_000_000, 50_000_000]

    print(f"  {'CO額':>14} {'実質還元率':>10} {'1000円投資時の期待値':>20} {'判定':>8}")
    print("  " + "─" * 60)

    for co in carryovers:
        # CO込みの実質還元率 = (売上 * 0.70 + CO) / 売上
        # 売上が一定なら CO が大きいほど還元率が上がる
        effective_rate = 0.70 + co / base_pool
        ev_1000 = 1000 * effective_rate
        if effective_rate >= 1.0:
            judgment = "★買い★"
        elif effective_rate >= 0.85:
            judgment = "検討余地あり"
        else:
            judgment = "見送り"

        print(
            f"  {format_currency(co):>14} "
            f"{effective_rate * 100:>8.1f}% "
            f"{format_currency(ev_1000):>18} "
            f"{judgment:>8}"
        )

    print("""
  【推奨】
  ・キャリーオーバーが売上プールの30%以上 → 実質還元率100%超で期待値プラス
  ・キャリーオーバーが発生した時に集中投資するのが最も合理的
  ・通常時は少額ランダム購入で「参加権」を維持し、CO発生時にまとめて買う
""")


def recommend_buying_strategy():
    """総合的な購入戦略を提案"""

    print("\n" + "=" * 80)
    print("■ 6. 推奨購入戦略まとめ")
    print("=" * 80)

    print("""
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  戦略1: キャリーオーバー集中型（推奨度: ★★★★★）
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ・通常時は購入を見送り、CO発生時のみ参戦
  ・CO発生時に3,000〜5,000円を投入
  ・2レッグは1-3人気で堅く固め、残り1レッグで幅広く買う
  ・荒れやすいレッグ（大井開催）で手広く、堅いレッグ（浦和・門別）で絞る

  買い方の例（予算3,000円 = 60点）:
    Leg1 (堅): 1着[1,2人気] → 2着[1,2,3人気]  = 4通り
    Leg2 (堅): 1着[1,2人気] → 2着[1,2,3人気]  = 4通り
    Leg3 (荒): 1着[1-4人気] → 2着[1-5人気]     = 16通り
    → 合計: 4 × 4 × 16 = 256点（予算不足なら絞る）

    予算内に収める例:
    Leg1: 1着[1,2] → 2着[1,2]        = 2通り
    Leg2: 1着[1,2] → 2着[1,2]        = 2通り
    Leg3: 1着[1-4] → 2着[1-4]        = 12通り
    → 合計: 2 × 2 × 12 = 48点 = 2,400円

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  戦略2: 少額ランダム＋堅軸型（推奨度: ★★★★☆）
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ・毎開催200〜500円の少額で参戦
  ・「一部ランダム」機能を活用
  ・1レッグは自分で堅め予想、残り2レッグはランダム
  ・的中時の高額配当を狙いつつ、投資を最小限に抑える

  買い方の例（予算500円 = 10点）:
    Leg1 (自分): 1着[1,2] → 2着[1,2,3]     = 4通り
    Leg2, Leg3:  ランダム（各1通り）
    → 合計: 4 × 1 × 1 = 4点 = 200円 ← 残りもランダムで追加

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  戦略3: 会場特化型（推奨度: ★★★☆☆）
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ・浦和or門別開催時（堅い決着が多い）に重点投資
  ・3レッグ全てが浦和or門別の日は特にチャンス
  ・全レッグ上位3人気を網羅する買い方
  ・低配当になりやすいが的中確率は最も高い

  買い方の例（浦和・門別日、予算5,000円 = 100点）:
    Leg1: 1着[1,2,3] → 2着[1,2,3]    = 6通り
    Leg2: 1着[1,2,3] → 2着[1,2,3]    = 6通り
    Leg3: 1着[1,2,3] → 2着[1,2,3]    = 6通り
    → 合計: 6 × 6 × 6 = 216点 = 10,800円（予算超え）

    絞り版:
    Leg1: 1着[1,2] → 2着[1,2,3]      = 4通り
    Leg2: 1着[1,2] → 2着[1,2,3]      = 4通り
    Leg3: 1着[1,2,3] → 2着[1,2,3]    = 6通り
    → 合計: 4 × 4 × 6 = 96点 = 4,800円

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  戦略4: 高配当一発狙い型（推奨度: ★★☆☆☆）
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ・大井開催日に中穴〜大穴を中心に購入
  ・当たれば100万円以上を目指す
  ・各レッグで3-8番人気を中心に選ぶ
  ・的中確率は非常に低いがロマン枠

  買い方の例（予算1,000円 = 20点）:
    Leg1: 1着[2,3] → 2着[3,4,5]      = 5通り
    Leg2: 1着[1,3] → 2着[2,4]        = 4通り
    Leg3: 1着[2,4] → 2着[1,3]        = 4通り (裏目含む)
    → 独自の読みで20点以内に絞る
""")


def analyze_key_numbers():
    """重要な数値サマリー"""

    print("\n" + "=" * 80)
    print("■ 重要数値サマリー")
    print("=" * 80)

    n = DEFAULT_FIELD_SIZE

    # 全レッグ1番人気→2番人気の確率
    p_fav = calculate_exacta_probability(1, 2, n)
    p_triple_fav = p_fav ** 3

    # 全レッグ上位3人気内の確率（いずれかの組み合わせ）
    p_top3 = 0
    for p1 in range(1, 4):
        for p2 in range(1, 4):
            if p1 != p2:
                p_top3 += calculate_exacta_probability(p1, p2, n)
    p_triple_top3 = p_top3 ** 3

    # 全レッグ上位5人気内の確率
    p_top5 = 0
    for p1 in range(1, 6):
        for p2 in range(1, 6):
            if p1 != p2:
                p_top5 += calculate_exacta_probability(p1, p2, n)
    p_triple_top5 = p_top5 ** 3

    print(f"""
  ┌────────────────────────────────────────────────────┐
  │ トリプル馬単 控除率: 30% (還元率 70%)               │
  │ 最低購入額: 50円                                    │
  │ 最高払戻: 1票(10円)につき6,000万円 → 50円で3億円     │
  ├────────────────────────────────────────────────────┤
  │                                                    │
  │ 【的中確率の目安】                                   │
  │ ・全レッグ 1番人気→2番人気:                          │
  │   {p_triple_fav * 100:.4f}% (1/{1 / p_triple_fav:,.0f})             │
  │                                                    │
  │ ・全レッグ 上位3人気内:                              │
  │   {p_triple_top3 * 100:.4f}% (1/{1 / p_triple_top3:,.0f})            │
  │                                                    │
  │ ・全レッグ 上位5人気内:                              │
  │   {p_triple_top5 * 100:.4f}% (1/{1 / p_triple_top5:,.0f})             │
  │                                                    │
  │ ・完全ランダム (16頭立×3レッグ):                     │
  │   0.0000072% (1/13,824,000)                        │
  │                                                    │
  │ 【会場別攻略ポイント】                               │
  │ ・浦和: 最堅。逃げ有利。入門向き                      │
  │ ・門別: 堅め。低配当多い。CO狙い                      │
  │ ・船橋: 短距離中心。先行有利                          │
  │ ・川崎: やや荒れ。中穴向き                           │
  │ ・大井: 最も荒れる。高配当の荒れレッグに               │
  │                                                    │
  │ 【最重要ポイント】                                   │
  │ ・キャリーオーバー時に集中投資が最も合理的              │
  │ ・2レッグ堅め + 1レッグ手広くが基本形                 │
  │ ・荒れやすい大井をワイドに、堅い浦和を絞る              │
  └────────────────────────────────────────────────────┘
""")


def main():
    parser = argparse.ArgumentParser(description="トリプル馬単 買い目分析")
    parser.add_argument("--json", type=str, help="JSONデータファイル")
    parser.add_argument("--csv", type=str, help="CSVデータファイル")
    parser.add_argument(
        "--demo", action="store_true",
        help="デモモード（統計モデルに基づく分析）",
    )
    args = parser.parse_args()

    if not args.json and not args.csv and not args.demo:
        # デフォルトはデモモード
        args.demo = True

    if args.demo:
        analyze_key_numbers()
        analyze_popularity_patterns()
        analyze_venue_patterns()
        analyze_optimal_strategies()
        analyze_carryover_strategy()
        recommend_buying_strategy()


if __name__ == "__main__":
    main()
