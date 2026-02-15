"""CLI エントリーポイント - FX自動売買システム"""

import argparse
import logging
import sys

from fx_trader.config import settings


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_fetch(args):
    """市場データ取得"""
    from fx_trader.data_fetcher.fetcher import DataFetcher

    fetcher = DataFetcher()
    instruments = args.instruments.split(",") if args.instruments else None
    results = fetcher.fetch_all_instruments(
        granularity=args.granularity,
        from_date=args.from_date,
        to_date=args.to_date,
        instruments=instruments,
    )
    print("\n=== データ取得結果 ===")
    for inst, count in results.items():
        print(f"  {inst}: {count} 本")


def cmd_train(args):
    """モデル学習"""
    from fx_trader.features.builder import FeatureBuilder
    from fx_trader.model.registry import save_model
    from fx_trader.model.trainer import ModelTrainer
    from fx_trader.storage.repository import Repository

    repo = Repository()
    builder = FeatureBuilder(repo)
    trainer = ModelTrainer()

    instruments = args.instruments.split(",") if args.instruments else settings.DEFAULT_INSTRUMENTS

    for instrument in instruments:
        print(f"\n=== {instrument} のモデル学習 ===")
        X, y = builder.build_training_set(
            instrument=instrument,
            granularity=args.granularity,
            from_date=args.from_date,
            to_date=args.to_date,
            forward_periods=args.forward_periods,
        )

        if X.empty:
            print(f"  データなし、スキップ")
            continue

        print(f"  サンプル数: {len(X)}, 特徴量数: {X.shape[1]}")

        result = trainer.train(X, y)
        model_name = f"{instrument.lower()}_{args.granularity.lower()}_{args.model_name}"

        save_model(result["model"], model_name, {
            "instrument": instrument,
            "granularity": args.granularity,
            "from_date": args.from_date,
            "to_date": args.to_date,
            "forward_periods": args.forward_periods,
            "features": result["features"],
            "cv_scores": result["cv_scores"],
            "positive_rate": result["positive_rate"],
            "cv_mean_auc": sum(result["cv_scores"]) / len(result["cv_scores"]),
        })

        print(f"  CV ROC-AUC: {result['cv_scores']}")
        print(f"  Mean AUC: {sum(result['cv_scores']) / len(result['cv_scores']):.4f}")
        print(f"  Positive rate: {result['positive_rate']:.3f}")
        print(f"  Model saved: {model_name}")


def cmd_predict(args):
    """売買シグナル生成"""
    from fx_trader.model.predictor import ModelPredictor

    instruments = args.instruments.split(",") if args.instruments else settings.DEFAULT_INSTRUMENTS

    for instrument in instruments:
        model_name = f"{instrument.lower()}_{args.granularity.lower()}_{args.model_name}"
        try:
            predictor = ModelPredictor(model_name)
        except FileNotFoundError:
            print(f"  モデル未学習: {model_name}")
            continue

        signal = predictor.predict_signal(instrument, args.granularity, args.threshold)

        print(f"\n=== {instrument} ===")
        print(f"  シグナル: {signal['signal_type'].upper()}")
        print(f"  確信度:   {signal['confidence']:.3f}")
        print(f"  上昇確率: {signal['prob_up']:.3f}")
        print(f"  時刻:     {signal['timestamp']}")


def cmd_backtest(args):
    """バックテスト"""
    from fx_trader.model.evaluation import BacktestEvaluator

    instruments = args.instruments.split(",") if args.instruments else settings.DEFAULT_INSTRUMENTS

    for instrument in instruments:
        model_name = f"{instrument.lower()}_{args.granularity.lower()}_{args.model_name}"
        try:
            evaluator = BacktestEvaluator(model_name)
        except FileNotFoundError:
            print(f"  モデル未学習: {model_name}")
            continue

        print(f"\n=== {instrument} バックテスト ===")
        result = evaluator.run_backtest(
            instrument=instrument,
            granularity=args.granularity,
            from_date=args.from_date,
            to_date=args.to_date,
            threshold=args.threshold,
        )

        if not result or result.get("total_trades", 0) == 0:
            print("  取引なし")
            continue

        print(f"  取引回数:     {result['total_trades']}")
        print(f"  勝率:         {result['win_rate'] * 100:.1f}%")
        print(f"  Profit Factor: {result['profit_factor']:.2f}")
        print(f"  Sharpe Ratio:  {result['sharpe_ratio']:.2f}")
        print(f"  Max Drawdown:  {result['max_drawdown'] * 100:.1f}%")
        print(f"  ROI:           {result['roi'] * 100:.1f}%")
        print(f"  最終残高:      {result['final_balance']:,.0f} 円")


def cmd_trade(args):
    """自動売買実行"""
    from fx_trader.trading.executor import TradeExecutor

    instruments = args.instruments.split(",") if args.instruments else settings.DEFAULT_INSTRUMENTS

    # モデル名は最初の通貨ペアベースで（通貨ペアごとに別モデルがロードされる）
    executor = TradeExecutor(
        model_name=f"{instruments[0].lower()}_{args.granularity.lower()}_{args.model_name}",
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print("=== DRY RUN モード (注文は出しません) ===\n")
    else:
        print("=== LIVE モード (実際に注文します) ===\n")
        confirm = input("本当に実行しますか？ (yes/no): ")
        if confirm.lower() != "yes":
            print("キャンセルしました")
            return

    results = executor.execute_signals(
        instruments=instruments,
        granularity=args.granularity,
        threshold=args.threshold,
    )

    for r in results:
        inst = r["instrument"]
        sig = r["signal"]
        print(f"\n{inst}: {sig['signal_type'].upper()} (confidence={sig['confidence']:.3f})")
        if r["action"] == "executed":
            t = r["trade"]
            print(f"  → 発注: {t['side']} {t['units']} units @ {t['entry_price']:.5f}")
            print(f"    SL={t['stop_loss']:.5f}  TP={t['take_profit']:.5f}")
        elif r["action"] == "blocked":
            print(f"  → ブロック: {r.get('reason', '')}")
        else:
            print(f"  → アクションなし")


def cmd_models(args):
    """保存済みモデル一覧"""
    from fx_trader.model.registry import list_models

    models = list_models()
    if not models:
        print("保存済みモデルはありません")
        return

    print(f"\n=== 保存済みモデル ({len(models)}件) ===")
    for m in models:
        meta = m["metadata"]
        print(f"\n  {m['name']}")
        if meta:
            print(f"    通貨ペア:   {meta.get('instrument', '?')}")
            print(f"    足:         {meta.get('granularity', '?')}")
            print(f"    期間:       {meta.get('from_date', '?')} ~ {meta.get('to_date', '?')}")
            print(f"    Mean AUC:   {meta.get('cv_mean_auc', '?')}")
            print(f"    保存日時:   {meta.get('saved_at', '?')}")


def main():
    parser = argparse.ArgumentParser(
        description="FX自動売買システム (OANDA + LightGBM)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ")
    subparsers = parser.add_subparsers(dest="command", help="コマンド")

    # --- fetch ---
    p_fetch = subparsers.add_parser("fetch", help="市場データ取得")
    p_fetch.add_argument("--instruments", type=str, default=None, help="通貨ペア (カンマ区切り, 例: USD_JPY,EUR_USD)")
    p_fetch.add_argument("--granularity", type=str, default="H1", help="足の種類 (例: M15, H1, D)")
    p_fetch.add_argument("--from-date", type=str, default=None, help="開始日 (YYYY-MM-DD)")
    p_fetch.add_argument("--to-date", type=str, default=None, help="終了日 (YYYY-MM-DD)")

    # --- train ---
    p_train = subparsers.add_parser("train", help="モデル学習")
    p_train.add_argument("--instruments", type=str, default=None, help="通貨ペア")
    p_train.add_argument("--granularity", type=str, default="H1", help="足の種類")
    p_train.add_argument("--from-date", type=str, required=True, help="学習開始日")
    p_train.add_argument("--to-date", type=str, required=True, help="学習終了日")
    p_train.add_argument("--model-name", type=str, default="v1", help="モデル名サフィックス")
    p_train.add_argument("--forward-periods", type=int, default=5, help="予測先の足数")

    # --- predict ---
    p_predict = subparsers.add_parser("predict", help="売買シグナル生成")
    p_predict.add_argument("--instruments", type=str, default=None, help="通貨ペア")
    p_predict.add_argument("--granularity", type=str, default="H1", help="足の種類")
    p_predict.add_argument("--model-name", type=str, default="v1", help="モデル名サフィックス")
    p_predict.add_argument("--threshold", type=float, default=0.55, help="シグナル閾値")

    # --- backtest ---
    p_bt = subparsers.add_parser("backtest", help="バックテスト")
    p_bt.add_argument("--instruments", type=str, default=None, help="通貨ペア")
    p_bt.add_argument("--granularity", type=str, default="H1", help="足の種類")
    p_bt.add_argument("--from-date", type=str, default=None, help="開始日")
    p_bt.add_argument("--to-date", type=str, default=None, help="終了日")
    p_bt.add_argument("--model-name", type=str, default="v1", help="モデル名サフィックス")
    p_bt.add_argument("--threshold", type=float, default=0.55, help="シグナル閾値")

    # --- trade ---
    p_trade = subparsers.add_parser("trade", help="自動売買実行")
    p_trade.add_argument("--instruments", type=str, default=None, help="通貨ペア")
    p_trade.add_argument("--granularity", type=str, default="H1", help="足の種類")
    p_trade.add_argument("--model-name", type=str, default="v1", help="モデル名サフィックス")
    p_trade.add_argument("--threshold", type=float, default=0.55, help="シグナル閾値")
    p_trade.add_argument("--dry-run", action="store_true", default=True, help="DRYRUNモード (デフォルト)")
    p_trade.add_argument("--live", action="store_true", help="実際に発注する")

    # --- models ---
    subparsers.add_parser("models", help="保存済みモデル一覧")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    setup_logging(args.verbose)

    if args.command == "trade" and args.live:
        args.dry_run = False

    cmd_map = {
        "fetch": cmd_fetch,
        "train": cmd_train,
        "predict": cmd_predict,
        "backtest": cmd_backtest,
        "trade": cmd_trade,
        "models": cmd_models,
    }
    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
