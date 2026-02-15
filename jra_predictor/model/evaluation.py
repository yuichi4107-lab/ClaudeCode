import logging

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
