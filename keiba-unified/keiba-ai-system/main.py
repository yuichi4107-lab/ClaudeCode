"""帯広ばんえい競馬 単勝予想システム

使い方:
    # データ収集（過去1年分）
    python main.py scrape --start 2025-01-01 --end 2025-12-31

    # モデル学習
    python main.py train

    # 予測（本日のレース）
    python main.py predict

    # 予測（日付指定）
    python main.py predict --date 2026-03-14
"""

import argparse
import logging
import sys
from datetime import date, datetime, timedelta

import pandas as pd

from config.settings import MODELS_DIR, PROCESSED_DATA_DIR, RAW_DATA_DIR
from src.features.feature_engineering import FeatureEngineer
from src.model.predictor import BaneiPredictor
from src.scraper.banei_scraper import BaneiScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def cmd_scrape(args):
    """データ収集コマンド"""
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    logger.info("データ収集開始: %s 〜 %s", start, end)

    scraper = BaneiScraper()
    df = scraper.scrape_date_range(start, end)

    if df.empty:
        logger.error("データが取得できませんでした")
        sys.exit(1)

    scraper.save_data(df)
    logger.info("データ収集完了: %d 件", len(df))


def cmd_train(args):
    """モデル学習コマンド"""
    data_file = RAW_DATA_DIR / (args.input or "race_results.csv")

    if not data_file.exists():
        logger.error("データファイルが見つかりません: %s", data_file)
        logger.error("先に `python main.py scrape` を実行してください")
        sys.exit(1)

    logger.info("データ読み込み: %s", data_file)
    df = pd.read_csv(data_file)
    logger.info("読み込み完了: %d 件", len(df))

    # 特徴量生成
    logger.info("特徴量生成中...")
    fe = FeatureEngineer(df)
    features_df = fe.build_features()
    fe.save(features_df)
    logger.info("特徴量生成完了: %d カラム", len(features_df.columns))

    # モデル学習
    logger.info("モデル学習開始...")
    predictor = BaneiPredictor()
    results = predictor.train(features_df)
    predictor.save()

    # 特徴量重要度を表示
    importance = predictor.get_feature_importance()
    print("\n===== 特徴量重要度 =====")
    for _, row in importance.head(15).iterrows():
        print(f"  {row['feature']:30s}  {row['importance']:>6.0f}")

    print(f"\n===== 学習結果 =====")
    print(f"  平均的中率:  {results['avg_hit_rate']:.1%}")
    print(f"  標準偏差:    {results['std_hit_rate']:.1%}")
    print(f"  学習データ数: {results['num_samples']:,}")
    print(f"  特徴量数:    {results['num_features']}")


def cmd_predict(args):
    """予測コマンド"""
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = date.today()

    predictions = _load_predictions_for_date(args, target_date)

    # 結果表示
    print(f"\n{'='*60}")
    print(f"  帯広ばんえい競馬 単勝予想  {target_date}")
    print(f"{'='*60}")

    for (rd, rno), race in predictions.groupby(["race_date", "race_no"]):
        print(f"\n--- {rno}R ---")
        has_odds = race["odds"].notna().any()
        if has_odds:
            print(f"  {'順位':>4s}  {'馬番':>4s}  {'馬名':10s}  {'勝率':>6s}  {'ｵｯｽﾞ':>6s}  {'期待値':>6s}")
            print(f"  {'----':>4s}  {'----':>4s}  {'----------':10s}  {'------':>6s}  {'------':>6s}  {'------':>6s}")
        else:
            print(f"  {'順位':>4s}  {'馬番':>4s}  {'馬名':10s}  {'勝率':>8s}")
            print(f"  {'----':>4s}  {'----':>4s}  {'----------':10s}  {'--------':>8s}")

        for _, row in race.head(5).iterrows():
            rank = int(row["pred_rank"])
            num = int(row["horse_number"]) if pd.notna(row["horse_number"]) else "-"
            name = row["horse_name"][:10]
            prob = row["win_prob"]
            mark = "◎" if rank == 1 else "○" if rank == 2 else "▲" if rank == 3 else "  "

            if has_odds and pd.notna(row["odds"]):
                odds_val = row["odds"]
                expected = prob * odds_val
                ev_mark = "★" if expected > 1.0 else "  "
                print(f"  {mark}{rank:>2d}    {num:>4}  {name:10s}  {prob:>5.1%}  {odds_val:>5.1f}  {expected:>5.2f}{ev_mark}")
            else:
                print(f"  {mark}{rank:>2d}    {num:>4}  {name:10s}  {prob:>7.1%}")

    print(f"\n  ★ = 期待値 > 1.0（妙味あり）")
    print(f"{'='*60}")


def _load_predictions_for_date(args, target_date):
    """指定日の予測データを生成して返す共通処理"""
    predictor = BaneiPredictor()
    try:
        predictor.load()
    except FileNotFoundError:
        logger.error("学習済みモデルが見つかりません。先に `python main.py train` を実行してください")
        sys.exit(1)

    raw_file = RAW_DATA_DIR / "race_results.csv"

    if getattr(args, "from_csv", False):
        if not raw_file.exists():
            logger.error("データファイルが見つかりません: %s", raw_file)
            sys.exit(1)
        combined = pd.read_csv(raw_file)
        logger.info("CSVデータから %s のレースを抽出", target_date)
    else:
        logger.info("%s のレースデータを取得中...", target_date)
        scraper = BaneiScraper()
        df = scraper.scrape_date_range(target_date, target_date)
        if df.empty:
            logger.error("%s のレースデータがありません", target_date)
            sys.exit(1)
        if raw_file.exists():
            past_df = pd.read_csv(raw_file)
            combined = pd.concat([past_df, df], ignore_index=True)
        else:
            combined = df

    fe = FeatureEngineer(combined)
    features_df = fe.build_features()

    today_mask = features_df["race_date"] == pd.Timestamp(target_date)
    today_df = features_df[today_mask]

    if today_df.empty:
        logger.error("当日のデータが見つかりません")
        sys.exit(1)

    predictions = predictor.predict(today_df)

    # オッズ情報を結合
    merge_cols = ["race_date", "race_no", "horse_number"]
    if "odds" in today_df.columns:
        predictions = predictions.merge(
            today_df[merge_cols + ["odds"]],
            on=merge_cols,
            how="left",
        )
    else:
        predictions["odds"] = None

    return predictions


def _analyze_race(race_df):
    """レースごとの分析指標を計算する"""
    top1 = race_df[race_df["pred_rank"] == 1].iloc[0]
    top2 = race_df[race_df["pred_rank"] == 2].iloc[0]

    prob1 = top1["win_prob"]
    prob2 = top2["win_prob"]
    confidence = prob1 - prob2  # 1位と2位の確率差

    odds1 = top1["odds"] if pd.notna(top1["odds"]) else 0
    expected_value = prob1 * odds1 if odds1 > 0 else 0

    return {
        "top_horse": top1["horse_name"],
        "top_number": int(top1["horse_number"]) if pd.notna(top1["horse_number"]) else 0,
        "top_prob": prob1,
        "top_odds": odds1,
        "expected_value": expected_value,
        "confidence": confidence,
        "num_runners": len(race_df),
    }


def _judge_race(analysis):
    """レースの購入推奨度を判定する

    判定基準:
    - S: 期待値1.5以上かつ信頼度(確率差)20%以上 → 強く推奨
    - A: 期待値1.2以上かつ信頼度15%以上 → 推奨
    - B: 期待値1.0以上 → やや推奨
    - C: 上記に該当しない → 見送り
    """
    ev = analysis["expected_value"]
    conf = analysis["confidence"]

    if ev >= 1.5 and conf >= 0.20:
        return "S"
    elif ev >= 1.2 and conf >= 0.15:
        return "A"
    elif ev >= 1.0:
        return "B"
    else:
        return "C"


def cmd_recommend(args):
    """推奨馬券コマンド（1R〜12R + 購入レース選定）

    期待値（勝率×オッズ）> 1.0 の馬すべてを単勝購入対象とする。
    """
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = date.today()

    predictions = _load_predictions_for_date(args, target_date)

    # --- 全レース予想 ---
    race_groups = list(predictions.groupby(["race_date", "race_no"]))

    # 各レースの購入対象馬を収集
    all_buy_tickets = []  # [(rno, number, name, prob, odds, ev), ...]

    print(f"\n{'='*64}")
    print(f"  帯広ばんえい競馬 単勝推奨馬券  {target_date}")
    print(f"{'='*64}")

    for (rd, rno), race in race_groups:
        has_odds = race["odds"].notna().any()

        # このレースの購入対象馬（期待値 > 1.0）を抽出
        race_tickets = []
        if has_odds:
            for _, row in race.iterrows():
                if pd.notna(row["odds"]) and row["odds"] > 0:
                    ev = row["win_prob"] * row["odds"]
                    if ev > 1.0:
                        race_tickets.append({
                            "rno": rno,
                            "number": int(row["horse_number"]) if pd.notna(row["horse_number"]) else 0,
                            "name": row["horse_name"],
                            "prob": row["win_prob"],
                            "odds": row["odds"],
                            "ev": ev,
                            "rank": int(row["pred_rank"]),
                        })

        num_tickets = len(race_tickets)
        if num_tickets > 0:
            label = f"購入{num_tickets}点"
        else:
            label = "見送り"

        print(f"\n--- {rno}R [{label}] ---")

        if has_odds:
            print(f"    {'馬番':>4s}  {'馬名':10s}  {'勝率':>6s}  {'ｵｯｽﾞ':>6s}  {'期待値':>6s}")
            print(f"    {'----':>4s}  {'----------':10s}  {'------':>6s}  {'------':>6s}  {'------':>6s}")
        else:
            print(f"    {'馬番':>4s}  {'馬名':10s}  {'勝率':>8s}")
            print(f"    {'----':>4s}  {'----------':10s}  {'--------':>8s}")

        for _, row in race.head(5).iterrows():
            rank = int(row["pred_rank"])
            num = int(row["horse_number"]) if pd.notna(row["horse_number"]) else "-"
            name = row["horse_name"][:10]
            prob = row["win_prob"]
            mark = "◎" if rank == 1 else "○" if rank == 2 else "▲" if rank == 3 else "  "

            if has_odds and pd.notna(row["odds"]):
                odds_val = row["odds"]
                expected = prob * odds_val
                ev_mark = "★" if expected > 1.0 else "  "
                print(f"  {mark} {num:>4}  {name:10s}  {prob:>5.1%}  {odds_val:>5.1f}  {expected:>5.2f}{ev_mark}")
            else:
                print(f"  {mark} {num:>4}  {name:10s}  {prob:>7.1%}")

        all_buy_tickets.extend(race_tickets)

    # --- 購入馬券まとめ ---
    print(f"\n{'='*64}")
    print(f"  購入馬券一覧（単勝 期待値 > 1.0）")
    print(f"{'='*64}")
    print()

    if all_buy_tickets:
        # レースごとにグループ化して表示
        from itertools import groupby as igroupby
        sorted_tickets = sorted(all_buy_tickets, key=lambda x: (str(x["rno"]).zfill(3), -x["ev"]))

        buy_races = set()
        total_tickets = 0

        for rno, tickets in igroupby(sorted_tickets, key=lambda x: x["rno"]):
            tickets = list(tickets)
            buy_races.add(rno)
            print(f"  {str(rno):>2s}R:")
            for t in tickets:
                total_tickets += 1
                print(
                    f"      {t['number']:>2d}番 {t['name'][:8]:8s}"
                    f"  勝率{t['prob']:>5.1%}  ｵｯｽﾞ{t['odds']:>5.1f}"
                    f"  期待値{t['ev']:>5.2f}"
                )
            print()

        skip_races = [rno for (_, rno), _ in race_groups if rno not in buy_races]
        if skip_races:
            print(f"  見送り: {', '.join(str(r) + 'R' for r in skip_races)}")
            print()

        total_cost = total_tickets * 100
        print(f"{'='*64}")
        print(f"  購入レース:  {len(buy_races)} / {len(race_groups)} レース")
        print(f"  購入点数:    {total_tickets} 点")
        print(f"  合計投資額:  {total_cost:,}円（単勝各100円）")
        print(f"{'='*64}")
    else:
        print("  本日は購入推奨馬券がありません。")
        print(f"\n{'='*64}")


def cmd_evaluate(args):
    """バックテスト（回収率シミュレーション）コマンド"""
    data_file = RAW_DATA_DIR / (args.input or "race_results.csv")

    if not data_file.exists():
        logger.error("データファイルが見つかりません: %s", data_file)
        sys.exit(1)

    df = pd.read_csv(data_file)
    fe = FeatureEngineer(df)
    features_df = fe.build_features()

    # 後半をテストデータとして使う（時系列分割）
    split_ratio = 1 - args.test_ratio
    race_dates = sorted(features_df["race_date"].unique())
    split_idx = int(len(race_dates) * split_ratio)
    train_dates = race_dates[:split_idx]
    test_dates = race_dates[split_idx:]

    train_df = features_df[features_df["race_date"].isin(train_dates)]
    test_df = features_df[features_df["race_date"].isin(test_dates)]

    logger.info("学習: %d レース日, テスト: %d レース日", len(train_dates), len(test_dates))

    predictor = BaneiPredictor()
    predictor.train(train_df)

    predictions = predictor.predict(test_df)

    # テストデータにオッズと着順を結合
    merge_cols = ["race_date", "race_no", "horse_number"]
    eval_df = predictions.merge(
        test_df[merge_cols + ["odds", "finish_order"]],
        on=merge_cols,
        how="left",
    )

    # 期待値 > 1.0 の馬すべてに単勝100円ずつ賭けた場合のシミュレーション
    total_bet = 0
    total_return = 0
    total_tickets = 0
    correct = 0
    total_races = 0
    bet_races = set()

    print(f"\n{'='*60}")
    print(f"  バックテスト結果")
    print(f"  テスト期間: {test_dates[0]} 〜 {test_dates[-1]}")
    print(f"  購入条件: 期待値（勝率×オッズ）> 1.0 の馬すべて")
    print(f"{'='*60}")

    for (rd, rno), race in eval_df.groupby(["race_date", "race_no"]):
        total_races += 1
        for _, row in race.iterrows():
            if pd.notna(row["odds"]) and row["odds"] > 0:
                ev = row["win_prob"] * row["odds"]
                if ev > 1.0:
                    total_bet += 100
                    total_tickets += 1
                    bet_races.add((rd, rno))
                    if row["finish_order"] == 1:
                        payout = 100 * row["odds"]
                        total_return += payout
                        correct += 1

    hit_rate = correct / total_tickets if total_tickets > 0 else 0
    return_rate = total_return / total_bet if total_bet > 0 else 0

    print(f"\n  全レース数:   {total_races}")
    print(f"  購入レース数: {len(bet_races)}")
    print(f"  購入点数:     {total_tickets}")
    print(f"  的中数:       {correct}")
    print(f"  的中率:       {hit_rate:.1%}")
    print(f"  総賭金:       {total_bet:,.0f}円")
    print(f"  総払戻:       {total_return:,.0f}円")
    print(f"  回収率:       {return_rate:.1%}")
    print(f"  損益:         {total_return - total_bet:+,.0f}円")
    print(f"\n{'='*60}")


def main():
    parser = argparse.ArgumentParser(
        description="帯広ばんえい競馬 単勝予想システム"
    )
    subparsers = parser.add_subparsers(dest="command", help="サブコマンド")

    # scrape
    sp_scrape = subparsers.add_parser("scrape", help="レースデータを収集する")
    sp_scrape.add_argument("--start", required=True, help="開始日 (YYYY-MM-DD)")
    sp_scrape.add_argument("--end", required=True, help="終了日 (YYYY-MM-DD)")

    # train
    sp_train = subparsers.add_parser("train", help="予測モデルを学習する")
    sp_train.add_argument("--input", help="入力CSVファイル名（デフォルト: race_results.csv）")

    # predict
    sp_predict = subparsers.add_parser("predict", help="レース結果を予測する")
    sp_predict.add_argument("--date", help="予測日 (YYYY-MM-DD, デフォルト: 本日)")
    sp_predict.add_argument(
        "--from-csv",
        action="store_true",
        help="スクレイピングせず既存CSVデータから予測する",
    )

    # recommend
    sp_rec = subparsers.add_parser("recommend", help="推奨馬券（購入レース選定付き）")
    sp_rec.add_argument("--date", help="予測日 (YYYY-MM-DD, デフォルト: 本日)")
    sp_rec.add_argument(
        "--from-csv",
        action="store_true",
        help="スクレイピングせず既存CSVデータから予測する",
    )

    # evaluate
    sp_eval = subparsers.add_parser("evaluate", help="バックテスト（回収率シミュレーション）")
    sp_eval.add_argument("--input", help="入力CSVファイル名（デフォルト: race_results.csv）")
    sp_eval.add_argument(
        "--test-ratio",
        type=float,
        default=0.2,
        help="テストデータの割合（デフォルト: 0.2）",
    )

    args = parser.parse_args()

    if args.command == "scrape":
        cmd_scrape(args)
    elif args.command == "train":
        cmd_train(args)
    elif args.command == "predict":
        cmd_predict(args)
    elif args.command == "recommend":
        cmd_recommend(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
