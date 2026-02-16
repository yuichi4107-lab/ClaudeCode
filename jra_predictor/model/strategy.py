"""
選択的ベッティング戦略モジュール。

全レースに賭けるのではなく、モデルの自信度が高いレースだけを選んで購入する。
目標: 1日4〜6レースに絞り、回収率 150% を狙う。

自信度スコア (confidence_score) の計算:
  1. edge_ratio: モデルの予測確率 / ランダム確率（モデルの優位性）
  2. separation: 1位予測と2位予測の確率差（予測の確信度）
  3. confidence_score = edge_ratio × (1 + separation / top1_prob)

三連複ボックス用:
  - top_sum: 選出馬のP(top3)合計値。高いほどモデルが上位馬を明確に識別
  - gap: 選出馬の最下位と次点の差。ボックスの境界が明確か
  - confidence_score = (top_sum / 3) × (1 + gap) × box_edge
"""

import logging
from math import comb

import pandas as pd

logger = logging.getLogger(__name__)


def score_quinella_race(ranked_df: pd.DataFrame, field_size: int) -> dict:
    """
    馬連予測結果からレースの自信度スコアを算出する。

    ranked_df: predict_quinella() の戻り値（上位N組の確率）
    field_size: 出走頭数
    """
    if len(ranked_df) < 2 or field_size < 2:
        return {"confidence_score": 0.0, "edge_ratio": 0.0, "separation": 0.0}

    top1_prob = ranked_df.iloc[0]["quinella_prob"]
    top2_prob = ranked_df.iloc[1]["quinella_prob"]
    # 馬連の組み合わせ数: C(n,2) = n*(n-1)/2
    random_prob = 2.0 / (field_size * (field_size - 1))

    edge_ratio = top1_prob / max(random_prob, 1e-9)
    separation = top1_prob - top2_prob

    confidence_score = edge_ratio * (1.0 + separation / max(top1_prob, 1e-9))

    return {
        "confidence_score": round(confidence_score, 4),
        "edge_ratio": round(edge_ratio, 4),
        "separation": round(separation, 6),
        "top1_prob": round(top1_prob, 6),
        "random_prob": round(random_prob, 6),
        "field_size": field_size,
    }


def score_quinella_box_race(
    selected_horses: list[dict],
    box_size: int,
    field_size: int,
    all_scores: list[float],
) -> dict:
    """
    馬連ボックスにおけるレースの自信度スコアを算出する。

    selected_horses: 選出馬リスト（win_prob, place_prob, score 含む）
    box_size: ボックスサイズ (3, 4, or 5)
    field_size: 出走頭数
    all_scores: 全馬のスコア (win_prob+place_prob) ソート済み降順

    スコアの考え方:
      - top_sum: 選出馬のスコア合計。高いほど有力馬が集中
      - gap: ボックス内最下位とボックス外最上位の差。大きいほど境界が明確
      - box_edge: ボックス的中確率 / ランダムボックス確率
    """
    if len(selected_horses) < box_size or field_size < box_size:
        return {"confidence_score": 0.0, "top_sum": 0.0, "gap": 0.0, "box_edge": 0.0}

    top_scores = [h["score"] for h in selected_horses]
    top_sum = sum(top_scores)

    # ボックス内最下位 vs ボックス外最上位の差
    if len(all_scores) > box_size:
        gap = all_scores[box_size - 1] - all_scores[box_size]
    else:
        gap = all_scores[box_size - 1]

    # ボックス的中確率の近似
    n_total_combos = comb(field_size, 2)
    n_box_combos = comb(box_size, 2)
    random_box_prob = n_box_combos / max(n_total_combos, 1)

    # 最大の組み合わせ確率
    from itertools import combinations as combs
    win_probs = [h["win_prob"] for h in selected_horses]
    place_probs = [h["place_prob"] for h in selected_horses]
    max_combo_prob = 0.0
    for ci, cj in combs(range(len(win_probs)), 2):
        pi = win_probs[ci]
        pj = win_probs[cj]
        di = max(1 - pi, 1e-6)
        dj = max(1 - pj, 1e-6)
        p = pi * place_probs[cj] / di + pj * place_probs[ci] / dj
        max_combo_prob = max(max_combo_prob, p)

    box_edge = max_combo_prob / max(random_box_prob / n_box_combos, 1e-9)

    confidence_score = (top_sum / 2.0) * (1.0 + gap) * max(box_edge, 1.0)

    return {
        "confidence_score": round(confidence_score, 4),
        "top_sum": round(top_sum, 4),
        "gap": round(gap, 4),
        "box_edge": round(box_edge, 4),
        "field_size": field_size,
        "box_size": box_size,
        "n_tickets": n_box_combos,
    }


def score_trio_race(ranked_df: pd.DataFrame, field_size: int) -> dict:
    """
    三連複予測結果からレースの自信度スコアを算出する。
    """
    if len(ranked_df) < 2 or field_size < 3:
        return {"confidence_score": 0.0, "edge_ratio": 0.0, "separation": 0.0}

    top1_prob = ranked_df.iloc[0]["trio_prob"]
    top2_prob = ranked_df.iloc[1]["trio_prob"]
    n_combos = comb(field_size, 3)
    random_prob = 1.0 / max(n_combos, 1)

    edge_ratio = top1_prob / max(random_prob, 1e-9)
    separation = top1_prob - top2_prob

    confidence_score = edge_ratio * (1.0 + separation / max(top1_prob, 1e-9))

    return {
        "confidence_score": round(confidence_score, 4),
        "edge_ratio": round(edge_ratio, 4),
        "separation": round(separation, 6),
        "top1_prob": round(top1_prob, 6),
        "random_prob": round(random_prob, 6),
        "field_size": field_size,
    }


def score_trio_box_race(
    selected_horses: list[dict],
    box_size: int,
    field_size: int,
    all_top3_probs: list[float],
) -> dict:
    """
    三連複ボックスにおけるレースの自信度スコアを算出する。

    selected_horses: 選出馬リスト（top3_prob 含む）
    box_size: ボックスサイズ (4 or 5)
    field_size: 出走頭数
    all_top3_probs: 全馬のP(top3) ソート済み降順

    スコアの考え方:
      - top_sum: 選出馬のP(top3)合計。3を超えるほど有力馬が集中
      - gap: ボックス内最下位とボックス外最上位の差。大きいほど境界が明確
      - box_edge: ボックス的中確率 / ランダムボックス確率
    """
    if len(selected_horses) < box_size or field_size < box_size:
        return {"confidence_score": 0.0, "top_sum": 0.0, "gap": 0.0, "box_edge": 0.0}

    top_probs = [h["top3_prob"] for h in selected_horses]
    top_sum = sum(top_probs)

    # ボックス内最下位 vs ボックス外最上位の差
    if len(all_top3_probs) > box_size:
        gap = all_top3_probs[box_size - 1] - all_top3_probs[box_size]
    else:
        gap = all_top3_probs[box_size - 1]

    # ボックス的中確率の近似: 選出馬のうち3頭が3着以内に入る確率
    # 全C(box,3)組の中で最大のもの（最も確率が高い3頭組）
    from itertools import combinations as combs
    max_combo_prob = 0.0
    for combo in combs(top_probs, 3):
        p = combo[0] * combo[1] * combo[2]
        max_combo_prob = max(max_combo_prob, p)

    # ランダムにbox_size頭選んだときの的中確率
    n_total_combos = comb(field_size, 3)
    n_box_combos = comb(box_size, 3)
    random_box_prob = n_box_combos / max(n_total_combos, 1)

    box_edge = max_combo_prob / max(random_box_prob / n_box_combos, 1e-9)

    confidence_score = (top_sum / 3.0) * (1.0 + gap) * max(box_edge, 1.0)

    return {
        "confidence_score": round(confidence_score, 4),
        "top_sum": round(top_sum, 4),
        "gap": round(gap, 4),
        "box_edge": round(box_edge, 4),
        "field_size": field_size,
        "box_size": box_size,
        "n_tickets": n_box_combos,
    }


def select_races(
    race_scores: list[dict],
    max_races: int = 6,
    min_confidence: float = 0.0,
    min_field_size: int = 0,
    max_field_size: int = 99,
) -> list[dict]:
    """
    自信度スコア上位のレースを max_races 件まで選出する。

    race_scores: score_*_race の結果リスト
                 （各 dict に race_id, confidence_score 等を含む）
    max_races: 1日あたり最大購入レース数
    min_confidence: 最低自信度スコア（これ未満は除外）
    min_field_size: 最小出走頭数フィルタ
    max_field_size: 最大出走頭数フィルタ
    """
    filtered = [
        s for s in race_scores
        if s["confidence_score"] >= min_confidence
        and s.get("field_size", 0) >= min_field_size
        and s.get("field_size", 99) <= max_field_size
    ]

    sorted_scores = sorted(filtered, key=lambda x: x["confidence_score"], reverse=True)
    return sorted_scores[:max_races]


def print_race_selection(selected: list[dict], bet_type: str = "quinella", box_size: int = 0) -> None:
    """選択されたレースの自信度情報を出力する。"""
    if bet_type == "trio" and box_size > 0:
        label = f"三連複{box_size}頭BOX"
        n_tickets = comb(box_size, 3)
    elif bet_type == "trio":
        label = "三連複"
    else:
        label = "馬連"

    print(f"\n=== {label} 厳選レース ({len(selected)}R) ===")

    if bet_type == "trio" and box_size > 0:
        print(f"{'No':>3} {'Race ID':>14} {'会場':>6} {'R':>3} {'頭数':>4} "
              f"{'自信度':>8} {'Top合計':>8} {'Gap':>6} {'点数':>4}")
        print("-" * 72)
        for i, s in enumerate(selected, 1):
            print(
                f"{i:3d} {s.get('race_id', ''):>14} "
                f"{s.get('venue', ''):>6} "
                f"{s.get('race_number', '?'):>3} "
                f"{s.get('field_size', 0):>4} "
                f"{s['confidence_score']:>8.2f} "
                f"{s.get('top_sum', 0):>8.3f} "
                f"{s.get('gap', 0):>6.3f} "
                f"{s.get('n_tickets', n_tickets):>4}"
            )
    else:
        print(f"{'No':>3} {'Race ID':>14} {'会場':>6} {'R':>3} {'頭数':>4} "
              f"{'自信度':>8} {'優位率':>8} {'Top1確率':>10} {'ランダム':>10}")
        print("-" * 80)
        for i, s in enumerate(selected, 1):
            print(
                f"{i:3d} {s.get('race_id', ''):>14} "
                f"{s.get('venue', ''):>6} "
                f"{s.get('race_number', '?'):>3} "
                f"{s.get('field_size', 0):>4} "
                f"{s['confidence_score']:>8.2f} "
                f"{s['edge_ratio']:>7.1f}x "
                f"{s['top1_prob']:>10.4f} "
                f"{s['random_prob']:>10.6f}"
            )
