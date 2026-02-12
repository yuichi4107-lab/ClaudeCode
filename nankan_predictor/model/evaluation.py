import logging

import pandas as pd

logger = logging.getLogger(__name__)


def evaluate_exacta_roi(predictions_df: pd.DataFrame, repo) -> dict:
    """
    予測上位の馬単組み合わせに賭けた場合のROIをシミュレーションする。

    predictions_df の必要列:
        race_id, first_horse_number, second_horse_number, exacta_prob

    repo: Repository（馬単払戻金の取得に使用）
    """
    results = []
    for race_id, group in predictions_df.groupby("race_id"):
        top = group.nlargest(1, "exacta_prob").iloc[0]
        first = int(top["first_horse_number"])
        second = int(top["second_horse_number"])

        payout = repo.get_exacta_payout(race_id, first, second)
        hit = payout is not None and payout > 0

        results.append(
            {
                "race_id": race_id,
                "hit": hit,
                "payout": payout / 100.0 if hit else 0.0,  # 100円単位を1単位に換算
            }
        )

    df = pd.DataFrame(results)
    invested = len(df)
    if invested == 0:
        return {"error": "No races found"}

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


def print_evaluation(result: dict) -> None:
    print("\n=== バックテスト結果（馬単） ===")
    if "error" in result:
        print(f"エラー: {result['error']}")
        return
    print(f"対象レース数: {result.get('total_races', 0)}")
    print(f"的中数:       {result.get('hits', 0)}")
    print(f"的中率:       {result.get('hit_rate', 0):.1%}")
    print(f"投資金額:     {result.get('total_invested', 0)} 単位")
    print(f"回収金額:     {result.get('total_returned', 0):.1f} 単位")
    print(f"ROI:          {result.get('roi', 0):+.1%}")
