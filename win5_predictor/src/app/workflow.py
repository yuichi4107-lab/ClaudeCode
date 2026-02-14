"""エンドツーエンドのワークフロー

CLI・Streamlitから呼び出される統合パイプライン。
"""

import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from config.settings import DB_PATH, DEFAULT_BUDGET, MODELS_DIR
from database.connection import db
from database.repository import Repository

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO"):
    """ロギングの初期設定"""
    from config.settings import LOG_FORMAT
    logging.basicConfig(format=LOG_FORMAT, level=getattr(logging, level, logging.INFO))


def collect_data(
    start: date, end: date, profiles: bool = True, cache: bool = True
):
    """データ収集パイプライン"""
    from scraper.scheduler import DataCollector

    setup_logging()
    collector = DataCollector(use_cache=cache)
    collector.collect_range(start, end, collect_profiles=profiles)


def train_model(
    start: date,
    end: date,
    include_odds: bool = True,
    optimize_hyperparams: bool = False,
    n_trials: int = 50,
) -> str:
    """モデル学習パイプライン

    Returns:
        model_id
    """
    setup_logging()
    db.initialize()

    repo = Repository()
    from features.builder import FeatureBuilder

    builder = FeatureBuilder(repo=repo)

    logger.info("Building training data: %s to %s", start, end)
    train_df = builder.build_training_data(start, end, include_odds=include_odds)

    if train_df.empty:
        raise RuntimeError("No training data found. Collect data first.")

    feature_cols = [
        c for c in train_df.columns if not c.startswith("_") and c != "target"
    ]
    logger.info("Training with %d samples, %d features", len(train_df), len(feature_cols))

    from model.trainer import LightGBMTrainer

    params = None
    if optimize_hyperparams:
        from model.hyperopt import HyperOptimizer

        logger.info("Running hyperparameter optimization (%d trials)...", n_trials)
        optimizer = HyperOptimizer()
        params = optimizer.optimize(
            train_df, feature_cols, n_trials=n_trials
        )

    trainer = LightGBMTrainer(params=params)
    trainer.train_with_timeseries_cv(train_df, feature_cols=feature_cols)

    from model.registry import ModelRegistry

    registry = ModelRegistry(repo=repo)
    model_id = registry.register_and_activate(
        trainer, train_start=start, train_end=end
    )

    # 特徴量重要度を表示
    importance = trainer.feature_importance(top_n=20)
    if not importance.empty:
        logger.info("Top 20 features:\n%s", importance.to_string(index=False))

    return model_id


def predict_win5(
    target_date: date,
    budget: int = DEFAULT_BUDGET,
    model_path: str | None = None,
) -> dict:
    """Win5予測パイプライン

    Returns:
        dict with predictions, ticket, ev_info, report
    """
    setup_logging()
    db.initialize()

    repo = Repository()

    from model.predictor import Predictor

    predictor = Predictor(
        model_path=model_path,
        repo=repo,
    )

    # Win5対象レース取得
    from scraper.win5_target import Win5TargetScraper

    scraper = Win5TargetScraper()
    race_ids = scraper.get_win5_race_ids(target_date)

    if len(race_ids) < 5:
        # DBから取得を試行
        event = repo.get_win5_event(target_date.strftime("%Y%m%d"))
        if event:
            race_ids = [
                event.race1_id, event.race2_id, event.race3_id,
                event.race4_id, event.race5_id,
            ]
            race_ids = [r for r in race_ids if r]

    if len(race_ids) < 5:
        raise RuntimeError(
            f"Could not find 5 Win5 races for {target_date}. "
            f"Found {len(race_ids)} races."
        )

    # 予測実行
    predictions = predictor.predict_win5_races(race_ids)

    # 最適買い目
    from optimizer.win5_combiner import Win5Combiner
    from optimizer.budget_optimizer import BudgetOptimizer
    from optimizer.expected_value import ExpectedValueCalculator

    combiner = Win5Combiner(predictions)
    optimizer = BudgetOptimizer(combiner, budget=budget)
    ticket = optimizer.optimize(max_per_race=6)

    # 期待値計算
    ev_calc = ExpectedValueCalculator()
    ev_info = ev_calc.calculate_ev(ticket) if ticket else {}

    # レポート生成
    from analysis.report import ReportGenerator

    reporter = ReportGenerator()
    ticket_info = {
        "num_combinations": ticket.num_combinations,
        "total_cost": ticket.total_cost,
        "hit_probability": ticket.total_hit_probability,
    } if ticket else None

    report = reporter.generate_prediction_report(
        target_date, predictions, ticket_info=ticket_info, ev_info=ev_info
    )

    return {
        "predictions": predictions,
        "ticket": ticket,
        "ev_info": ev_info,
        "report": report,
    }


def run_backtest(
    start: date,
    end: date,
    budget: int = DEFAULT_BUDGET,
    model_path: str | None = None,
) -> dict:
    """バックテストパイプライン"""
    setup_logging()
    db.initialize()

    repo = Repository()

    from model.predictor import Predictor
    from analysis.backtester import Backtester
    from analysis.roi_calculator import ROICalculator
    from analysis.visualizer import Visualizer
    from analysis.report import ReportGenerator

    predictor = Predictor(model_path=model_path, repo=repo)
    backtester = Backtester(predictor, repo=repo, budget=budget)

    results_df = backtester.run(start, end)

    if results_df.empty:
        logger.warning("No backtest results")
        return {"results": results_df}

    # 分析
    roi_calc = ROICalculator(results_df)
    roi_info = roi_calc.overall_roi()
    monthly = roi_calc.monthly_roi()
    drawdown = roi_calc.drawdown_analysis()
    cumulative = roi_calc.cumulative_profit()

    # 可視化
    viz = Visualizer()
    if not cumulative.empty:
        viz.plot_cumulative_profit(cumulative)
    if not monthly.empty:
        viz.plot_monthly_roi(monthly)

    # レポート
    reporter = ReportGenerator()
    report = reporter.generate_backtest_report(
        results_df, roi_info, drawdown, monthly
    )

    return {
        "results": results_df,
        "roi": roi_info,
        "monthly": monthly,
        "drawdown": drawdown,
        "report": report,
    }


def get_system_status() -> dict:
    """システムの状態を確認する"""
    db.initialize()
    repo = Repository()

    status = {
        "db_path": str(DB_PATH),
        "db_exists": Path(DB_PATH).exists(),
        "races_count": 0,
        "results_count": 0,
        "date_range": None,
        "active_model": None,
        "models_dir": str(MODELS_DIR),
    }

    try:
        status["races_count"] = repo.count_races()
        status["results_count"] = repo.count_results()
        status["date_range"] = repo.get_date_range()
    except Exception:
        pass

    model_info = repo.get_active_model()
    if model_info:
        status["active_model"] = {
            "model_id": model_info.model_id,
            "version": model_info.version,
            "auc": model_info.auc,
            "feature_count": model_info.feature_count,
        }

    return status
