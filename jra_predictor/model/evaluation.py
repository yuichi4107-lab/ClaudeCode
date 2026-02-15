import logging
from collections import defaultdict

import pandas as pd

logger = logging.getLogger(__name__)


def evaluate_exacta_roi(predictions_df: pd.DataFrame, repo, top_n: int = 1, threshold: float = 0.0) -> dict:
    """
    予測上位の馬単組み合わせに賭けた場合のROIをシミュレーションする。

    predictions_df の必要列:
        race_id, first_horse_number, second_horse_number, exacta_prob
    """
    results = []
    for race_id, group in predictions_df.groupby("race_id"):
        filtered = group[group["exacta_prob"] >= threshold]
        if len(filtered) == 0:
            continue

        top_combos = filtered.nlargest(top_n, "exacta_prob")

        for _, row in top_combos.iterrows():
            first = int(row["first_horse_number"])
            second = int(row["second_horse_number"])

            payout = repo.get_exacta_payout(race_id, first, second)
            hit = payout is not None and payout > 0

            results.append(
                {
                    "race_id": race_id,
                    "hit": hit,
                    "payout": payout / 100.0 if hit else 0.0,
                }
            )

    return _summarize(results)


def evaluate_trio_roi(predictions_df: pd.DataFrame, repo, top_n: int = 1, threshold: float = 0.0) -> dict:
    """
    予測上位の三連複組み合わせに賭けた場合のROIをシミュレーションする。

    predictions_df の必要列:
        race_id, horse1_number, horse2_number, horse3_number, trio_prob
    """
    results = []
    for race_id, group in predictions_df.groupby("race_id"):
        filtered = group[group["trio_prob"] >= threshold]
        if len(filtered) == 0:
            continue

        top_combos = filtered.nlargest(top_n, "trio_prob")

        for _, row in top_combos.iterrows():
            h1 = int(row["horse1_number"])
            h2 = int(row["horse2_number"])
            h3 = int(row["horse3_number"])

            payout = repo.get_trio_payout(race_id, h1, h2, h3)
            hit = payout is not None and payout > 0

            results.append(
                {
                    "race_id": race_id,
                    "hit": hit,
                    "payout": payout / 100.0 if hit else 0.0,
                }
            )

    return _summarize(results)


def evaluate_selective_roi(
    race_predictions: list[dict],
    repo,
    bet_type: str = "exacta",
    max_races_per_day: int = 6,
    min_confidence: float = 0.0,
    top_n_per_race: int = 1,
) -> dict:
    """
    選択的ベッティング戦略のバックテスト。

    race_predictions: list of {
        race_id, race_date, confidence_score,
        predictions: DataFrame (predict_exacta / predict_trio の結果)
    }
    max_races_per_day: 1日あたり最大購入レース数
    min_confidence: 最低自信度スコア
    top_n_per_race: 1レースあたりの購入組数
    """
    # 日別にグループ化してレース選択
    by_date = defaultdict(list)
    for rp in race_predictions:
        if rp["confidence_score"] < min_confidence:
            continue
        race_date = rp.get("race_date", rp["race_id"][:4] + "-" + rp["race_id"][6:8] + "-" + rp["race_id"][8:10])
        by_date[race_date].append(rp)

    results = []
    daily_stats = []

    for date, races in sorted(by_date.items()):
        # 自信度上位 max_races_per_day 件を選出
        selected = sorted(races, key=lambda x: x["confidence_score"], reverse=True)[:max_races_per_day]

        day_invested = 0
        day_returned = 0.0
        day_hits = 0

        for rp in selected:
            preds = rp["predictions"]
            race_id = rp["race_id"]

            if bet_type == "trio":
                top_combos = preds.nlargest(top_n_per_race, "trio_prob")
                for _, row in top_combos.iterrows():
                    h1 = int(row["horse1_number"])
                    h2 = int(row["horse2_number"])
                    h3 = int(row["horse3_number"])
                    payout = repo.get_trio_payout(race_id, h1, h2, h3)
                    hit = payout is not None and payout > 0
                    ret = payout / 100.0 if hit else 0.0
                    results.append({"race_id": race_id, "date": date, "hit": hit, "payout": ret,
                                    "confidence": rp["confidence_score"]})
                    day_invested += 1
                    day_returned += ret
                    if hit:
                        day_hits += 1
            else:
                top_combos = preds.nlargest(top_n_per_race, "exacta_prob")
                for _, row in top_combos.iterrows():
                    first = int(row["first_horse_number"])
                    second = int(row["second_horse_number"])
                    payout = repo.get_exacta_payout(race_id, first, second)
                    hit = payout is not None and payout > 0
                    ret = payout / 100.0 if hit else 0.0
                    results.append({"race_id": race_id, "date": date, "hit": hit, "payout": ret,
                                    "confidence": rp["confidence_score"]})
                    day_invested += 1
                    day_returned += ret
                    if hit:
                        day_hits += 1

        if day_invested > 0:
            daily_stats.append({
                "date": date,
                "races": len(selected),
                "bets": day_invested,
                "hits": day_hits,
                "invested": day_invested,
                "returned": day_returned,
                "roi": (day_returned - day_invested) / day_invested,
            })

    summary = _summarize(results)
    summary["daily_stats"] = daily_stats
    summary["avg_races_per_day"] = (
        sum(d["races"] for d in daily_stats) / len(daily_stats) if daily_stats else 0
    )
    summary["profitable_days"] = sum(1 for d in daily_stats if d["roi"] > 0)
    summary["total_days"] = len(daily_stats)
    return summary


def _summarize(results: list[dict]) -> dict:
    if not results:
        return {"error": "No bets placed (threshold too high or no data)"}

    df = pd.DataFrame(results)
    invested = len(df)
    returned = df["payout"].sum()
    hits = int(df["hit"].sum())

    return {
        "total_races": invested,
        "hits": hits,
        "hit_rate": hits / invested,
        "total_invested": invested,
        "total_returned": returned,
        "roi": (returned - invested) / invested,
    }


def print_evaluation(result: dict, bet_type: str = "exacta", top_n: int = 1, threshold: float = 0.0) -> None:
    label = "馬単" if bet_type == "exacta" else "三連複"
    print(f"\n=== バックテスト結果（{label}） ===")
    print(f"戦略: top_n={top_n}, threshold={threshold:.4f}")
    if "error" in result:
        print(f"エラー: {result['error']}")
        return
    print(f"対象レース数: {result.get('total_races', 0)}")
    print(f"的中数:       {result.get('hits', 0)}")
    print(f"的中率:       {result.get('hit_rate', 0):.1%}")
    print(f"投資金額:     {result.get('total_invested', 0)} 単位")
    print(f"回収金額:     {result.get('total_returned', 0):.1f} 単位")
    print(f"ROI:          {result.get('roi', 0):+.1%}")


def print_selective_evaluation(
    result: dict,
    bet_type: str = "exacta",
    max_races: int = 6,
    min_confidence: float = 0.0,
    top_n: int = 1,
    show_daily: bool = True,
) -> None:
    label = "馬単" if bet_type == "exacta" else "三連複"
    print(f"\n{'='*60}")
    print(f"  選択的ベッティング バックテスト結果（{label}）")
    print(f"{'='*60}")
    print(f"戦略: 1日最大{max_races}R, 最低自信度={min_confidence:.2f}, "
          f"1Rあたり{top_n}点購入")

    if "error" in result:
        print(f"エラー: {result['error']}")
        return

    print(f"\n--- 全体成績 ---")
    print(f"総ベット数:   {result.get('total_races', 0)}")
    print(f"的中数:       {result.get('hits', 0)}")
    print(f"的中率:       {result.get('hit_rate', 0):.1%}")
    print(f"投資金額:     {result.get('total_invested', 0)} 単位")
    print(f"回収金額:     {result.get('total_returned', 0):.1f} 単位")
    print(f"ROI:          {result.get('roi', 0):+.1%}")

    print(f"\n--- 日別サマリ ---")
    print(f"開催日数:     {result.get('total_days', 0)}")
    print(f"プラス日:     {result.get('profitable_days', 0)}")
    print(f"平均購入R/日: {result.get('avg_races_per_day', 0):.1f}")

    daily_stats = result.get("daily_stats", [])
    if show_daily and daily_stats:
        print(f"\n--- 日別詳細 ---")
        print(f"{'日付':>12} {'R数':>4} {'BET':>4} {'的中':>4} {'投資':>6} {'回収':>8} {'ROI':>8}")
        print("-" * 52)
        for d in daily_stats:
            roi_str = f"{d['roi']:+.0%}"
            marker = " **" if d["roi"] >= 0.5 else ""
            print(f"{d['date']:>12} {d['races']:>4} {d['bets']:>4} {d['hits']:>4} "
                  f"{d['invested']:>6} {d['returned']:>8.1f} {roi_str:>8}{marker}")
