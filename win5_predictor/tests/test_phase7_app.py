"""Phase 7: アプリケーション層のテスト

CLIインターフェース、ワークフロー、Streamlitダッシュボードの統合テスト
"""

import sys
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import Mock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# CLI tests
try:
    from click.testing import CliRunner
    CLICK_AVAILABLE = True
except ImportError:
    CLICK_AVAILABLE = False


def test_cli_version():
    """CLIバージョン確認テスト"""
    if not CLICK_AVAILABLE:
        pytest.skip("Click not available")

    from app.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])

    assert result.exit_code == 0, f"Version check failed: {result.output}"
    assert "win5-predictor" in result.output, "Version string should contain program name"
    print("✓ CLI version command works")
    return True


def test_cli_help():
    """CLIヘルプ表示テスト"""
    if not CLICK_AVAILABLE:
        pytest.skip("Click not available")

    from app.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0, "Help command should exit cleanly"
    assert "Usage:" in result.output or "usage:" in result.output.lower(), "Help output should contain usage"
    print("✓ CLI help display works")
    return True


def test_cli_collect_help():
    """CLIデータ収集コマンドのヘルプ"""
    if not CLICK_AVAILABLE:
        pytest.skip("Click not available")

    from app.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["collect", "--help"])

    assert result.exit_code == 0, "Collect help should work"
    assert "--start" in result.output, "Should have start option"
    assert "--end" in result.output, "Should have end option"
    print("✓ CLI collect help works")
    return True


def test_cli_train_help():
    """CLIモデル学習コマンドのヘルプ"""
    if not CLICK_AVAILABLE:
        pytest.skip("Click not available")

    from app.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["train", "--help"])

    assert result.exit_code == 0, "Train help should work"
    assert "--start" in result.output, "Should have start option"
    assert "--optimize" in result.output, "Should have optimize option"
    print("✓ CLI train help works")
    return True


def test_cli_predict_help():
    """CLIPredictコマンドのヘルプ"""
    if not CLICK_AVAILABLE:
        pytest.skip("Click not available")

    from app.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["predict", "--help"])

    assert result.exit_code == 0, "Predict help should work"
    assert "--date" in result.output, "Should have date option"
    assert "--budget" in result.output, "Should have budget option"
    print("✓ CLI predict help works")
    return True


def test_cli_backtest_help():
    """CLIバックテストコマンドのヘルプ"""
    if not CLICK_AVAILABLE:
        pytest.skip("Click not available")

    from app.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["backtest", "--help"])

    assert result.exit_code == 0, "Backtest help should work"
    assert "--start" in result.output, "Should have start option"
    assert "--end" in result.output, "Should have end option"
    print("✓ CLI backtest help works")
    return True


def test_cli_status_help():
    """CLIステータスコマンドのヘルプ"""
    if not CLICK_AVAILABLE:
        pytest.skip("Click not available")

    from app.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--help"])

    assert result.exit_code == 0, "Status help should work"
    print("✓ CLI status help works")
    return True


def test_cli_dashboard_help():
    """CLIダッシュボードコマンドのヘルプ"""
    if not CLICK_AVAILABLE:
        pytest.skip("Click not available")

    from app.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["dashboard", "--help"])

    assert result.exit_code == 0, "Dashboard help should work"
    assert "--port" in result.output, "Should have port option"
    print("✓ CLI dashboard help works")
    return True


def test_workflow_setup_logging():
    """ワークフロー: ログ設定テスト"""
    from app.workflow import setup_logging

    import logging

    setup_logging(level="DEBUG")

    logger = logging.getLogger("test")
    assert logger is not None, "Logger should be created"
    print("✓ Workflow logging setup works")
    return True


def test_workflow_systemstatus_mock():
    """ワークフロー: システムステータス取得（モック）"""
    with patch("app.workflow.db.initialize"), \
         patch("app.workflow.Repository") as MockRepo:

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo

        # モック値を設定
        mock_repo.count_races.return_value = 1000
        mock_repo.count_results.return_value = 5000
        mock_repo.get_date_range.return_value = (date(2023, 1, 1), date(2025, 12, 31))
        mock_repo.get_active_model.return_value = MagicMock(
            model_id="test-model",
            version=1,
            auc=0.672,
            feature_count=87,
        )

        from app.workflow import get_system_status
        status = get_system_status()

        assert "db_path" in status, "Status should have db_path"
        assert "db_exists" in status, "Status should have db_exists"
        assert "races_count" in status, "Status should have races_count"
        assert "results_count" in status, "Status should have results_count"
        assert "active_model" in status, "Status should have active_model"
        assert status["races_count"] == 1000, "Race count should match mock"
        assert status["results_count"] == 5000, "Result count should match mock"
        assert status["active_model"]["auc"] == 0.672, "AUC should match mock"

        print("✓ Workflow system status works")
        return True


def test_workflow_collect_data_params():
    """ワークフロー: データ収集パラメータ検証"""
    from app.workflow import collect_data

    with patch("app.workflow.DataCollector") as MockCollector:
        mock_collector = MagicMock()
        MockCollector.return_value = mock_collector

        start = date(2023, 1, 1)
        end = date(2023, 12, 31)

        collect_data(start, end, profiles=True, cache=True)

        # DataCollectorが正しいパラメータで呼び出されたか確認
        MockCollector.assert_called_once_with(use_cache=True)
        mock_collector.collect_range.assert_called_once_with(start, end, collect_profiles=True)

        print("✓ Workflow data collection calls with correct params")
        return True


def test_workflow_train_model_empty_data():
    """ワークフロー: 空データでのモデル学習テスト"""
    with patch("app.workflow.db.initialize"), \
         patch("app.workflow.Repository") as MockRepo, \
         patch("app.workflow.FeatureBuilder") as MockBuilder:

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo

        mock_builder = MagicMock()
        MockBuilder.return_value = mock_builder

        import pandas as pd
        mock_builder.build_training_data.return_value = pd.DataFrame()  # 空DataFrame

        from app.workflow import train_model

        with pytest.raises(RuntimeError, match="No training data found"):
            train_model(date(2023, 1, 1), date(2023, 12, 31))

        print("✓ Workflow raises error on empty training data")
        return True


def test_workflow_predict_win5_missing_races():
    """ワークフロー: Win5レースが不足する場合"""
    with patch("app.workflow.db.initialize"), \
         patch("app.workflow.Repository") as MockRepo, \
         patch("app.workflow.Predictor") as MockPredictor, \
         patch("app.workflow.Win5TargetScraper") as MockScraper:

        mock_scraper = MagicMock()
        MockScraper.return_value = mock_scraper
        mock_scraper.get_win5_race_ids.return_value = ["R1", "R2"]  # 2レース（5必要）

        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get_win5_event.return_value = None  # DBにも無い

        from app.workflow import predict_win5

        with pytest.raises(RuntimeError, match="Could not find 5 Win5 races"):
            predict_win5(date(2026, 2, 15))

        print("✓ Workflow raises error when Win5 races insufficient")
        return True


def test_workflow_predict_win5_success_mock():
    """ワークフロー: Win5予測成功（モック）"""
    with patch("app.workflow.db.initialize"), \
         patch("app.workflow.Repository") as MockRepo, \
         patch("app.workflow.Predictor") as MockPredictor, \
         patch("app.workflow.Win5TargetScraper") as MockScraper, \
         patch("app.workflow.Win5Combiner") as MockCombiner, \
         patch("app.workflow.BudgetOptimizer") as MockOptimizer, \
         patch("app.workflow.ExpectedValueCalculator") as MockEVCalc, \
         patch("app.workflow.ReportGenerator") as MockReporter:

        # Scraper mock
        mock_scraper = MagicMock()
        MockScraper.return_value = mock_scraper
        mock_scraper.get_win5_race_ids.return_value = ["R1", "R2", "R3", "R4", "R5"]

        # Predictor mock
        mock_predictor = MagicMock()
        MockPredictor.return_value = mock_predictor
        import pandas as pd
        mock_predictor.predict_win5_races.return_value = {
            f"R{i}": pd.DataFrame({"horse_number": [1,2,3], "calibrated_prob": [0.3, 0.2, 0.1]})
            for i in range(1, 6)
        }

        # Optimizer mock
        mock_optimizer = MagicMock()
        MockOptimizer.return_value = mock_optimizer
        mock_ticket = MagicMock()
        mock_ticket.num_combinations = 100
        mock_ticket.total_cost = 10000
        mock_ticket.total_hit_probability = 0.005
        mock_optimizer.optimize.return_value = mock_ticket

        # EV Calculator mock
        mock_ev_calc = MagicMock()
        MockEVCalc.return_value = mock_ev_calc
        mock_ev_calc.calculate_ev.return_value = {"expected_value": 5000}

        # Reporter mock
        mock_reporter = MagicMock()
        MockReporter.return_value = mock_reporter
        mock_reporter.generate_prediction_report.return_value = "Test Report"

        from app.workflow import predict_win5

        result = predict_win5(date(2026, 2, 15), budget=10000)

        assert "predictions" in result, "Result should have predictions"
        assert "ticket" in result, "Result should have ticket"
        assert "ev_info" in result, "Result should have ev_info"
        assert "report" in result, "Result should have report"
        assert result["report"] == "Test Report", "Report should match mock"

        print("✓ Workflow Win5 prediction works end-to-end")
        return True


def test_workflow_backtest_empty_results():
    """ワークフロー: バックテスト結果が空の場合"""
    with patch("app.workflow.db.initialize"), \
         patch("app.workflow.Repository") as MockRepo, \
         patch("app.workflow.Predictor") as MockPredictor, \
         patch("app.workflow.Backtester") as MockBacktester:

        mock_backtester = MagicMock()
        MockBacktester.return_value = mock_backtester
        import pandas as pd
        mock_backtester.run.return_value = pd.DataFrame()  # 空結果

        from app.workflow import run_backtest

        result = run_backtest(date(2023, 1, 1), date(2023, 12, 31))

        assert "results" in result, "Result should have results key"
        assert result["results"].empty, "Results should be empty"

        print("✓ Workflow handles empty backtest results")
        return True


def test_workflow_backtest_success_mock():
    """ワークフロー: バックテスト成功（モック）"""
    with patch("app.workflow.db.initialize"), \
         patch("app.workflow.Repository") as MockRepo, \
         patch("app.workflow.Predictor") as MockPredictor, \
         patch("app.workflow.Backtester") as MockBacktester, \
         patch("app.workflow.ROICalculator") as MockROICalc, \
         patch("app.workflow.Visualizer") as MockViz, \
         patch("app.workflow.ReportGenerator") as MockReporter:

        # Backtester mock
        mock_backtester = MagicMock()
        MockBacktester.return_value = mock_backtester
        import pandas as pd
        results_df = pd.DataFrame({
            "event_date": [date(2023, 1, 1), date(2023, 1, 8)],
            "num_combinations": [100, 100],
            "total_cost": [10000, 10000],
            "is_hit": [False, True],
            "actual_payout": [0, 800000],
            "profit": [-10000, 790000],
        })
        mock_backtester.run.return_value = results_df

        # ROI Calculator mock
        mock_roi_calc = MagicMock()
        MockROICalc.return_value = mock_roi_calc
        mock_roi_calc.overall_roi.return_value = {
            "roi": 3900.0,
            "total_cost": 20000,
            "total_payout": 800000,
            "profit": 780000,
        }
        mock_roi_calc.monthly_roi.return_value = pd.DataFrame()
        mock_roi_calc.cumulative_profit.return_value = pd.DataFrame()
        mock_roi_calc.drawdown_analysis.return_value = {"max_drawdown": -10000, "max_drawdown_pct": -50}

        # Reporter mock
        mock_reporter = MagicMock()
        MockReporter.return_value = mock_reporter
        mock_reporter.generate_backtest_report.return_value = "Backtest Report"

        from app.workflow import run_backtest

        result = run_backtest(date(2023, 1, 1), date(2023, 12, 31), budget=10000)

        assert "results" in result, "Result should have results"
        assert "roi" in result, "Result should have ROI"
        assert result["roi"]["roi"] == 3900.0, "ROI should match mock"
        assert result["roi"]["profit"] == 780000, "Profit should match mock"
        assert "report" in result, "Result should have report"

        print("✓ Workflow backtest works end-to-end")
        return True


def test_date_parsing():
    """日付パース関数テスト"""
    if not CLICK_AVAILABLE:
        pytest.skip("Click not available")

    from app.cli import _parse_date

    d = _parse_date("2026-02-15")
    assert isinstance(d, date), "Should return date object"
    assert d == date(2026, 2, 15), "Date should match input"

    with pytest.raises(ValueError):
        _parse_date("2026/02/15")  # 違う形式

    print("✓ Date parsing works")
    return True


def test_cli_contains_all_commands():
    """CLIが全てのコマンドを含むテスト"""
    if not CLICK_AVAILABLE:
        pytest.skip("Click not available")

    from app.cli import cli

    # CLIオブジェクトのコマンドをチェック
    assert "collect" in cli.commands, "Should have collect command"
    assert "train" in cli.commands, "Should have train command"
    assert "predict" in cli.commands, "Should have predict command"
    assert "backtest" in cli.commands, "Should have backtest command"
    assert "status" in cli.commands, "Should have status command"
    assert "dashboard" in cli.commands, "Should have dashboard command"

    print("✓ CLI contains all required commands")
    return True


def test_workflow_collect_data_with_profiles():
    """ワークフロー: 馬/騎手プロファイル込みデータ収集"""
    from app.workflow import collect_data

    with patch("app.workflow.DataCollector") as MockCollector:
        mock_collector = MagicMock()
        MockCollector.return_value = mock_collector

        # profiles=True の場合
        collect_data(date(2023, 1, 1), date(2023, 12, 31), profiles=True, cache=True)
        mock_collector.collect_range.assert_called_once_with(
            date(2023, 1, 1), date(2023, 12, 31), collect_profiles=True
        )

        print("✓ Workflow collect data with profiles flag works")
        return True


def test_workflow_collect_data_without_cache():
    """ワークフロー: キャッシュなしでデータ収集"""
    from app.workflow import collect_data

    with patch("app.workflow.DataCollector") as MockCollector:
        mock_collector = MagicMock()
        MockCollector.return_value = mock_collector

        # cache=False の場合
        collect_data(date(2023, 1, 1), date(2023, 12, 31), profiles=False, cache=False)

        MockCollector.assert_called_once_with(use_cache=False)

        print("✓ Workflow collect data without cache flag works")
        return True


def run_all_phase7_tests():
    """Phase 7 の全テストを実行"""
    print("\n" + "=" * 70)
    print("Phase 7: Application Layer (CLI, Workflow, Dashboard) - Test Suite")
    print("=" * 70)

    if not CLICK_AVAILABLE:
        print("\n⚠ Warning: Click is not installed.")
        print("Install with: pip install click")
        return False

    tests = [
        ("CLI Version Check", test_cli_version),
        ("CLI Help Display", test_cli_help),
        ("CLI Collect Help", test_cli_collect_help),
        ("CLI Train Help", test_cli_train_help),
        ("CLI Predict Help", test_cli_predict_help),
        ("CLI Backtest Help", test_cli_backtest_help),
        ("CLI Status Help", test_cli_status_help),
        ("CLI Dashboard Help", test_cli_dashboard_help),
        ("Workflow Logging Setup", test_workflow_setup_logging),
        ("Workflow System Status", test_workflow_systemstatus_mock),
        ("Workflow Collect Data Params", test_workflow_collect_data_params),
        ("Workflow Train Model Empty Data", test_workflow_train_model_empty_data),
        ("Workflow Predict Win5 Missing Races", test_workflow_predict_win5_missing_races),
        ("Workflow Predict Win5 Success", test_workflow_predict_win5_success_mock),
        ("Workflow Backtest Empty Results", test_workflow_backtest_empty_results),
        ("Workflow Backtest Success", test_workflow_backtest_success_mock),
        ("Date Parsing", test_date_parsing),
        ("CLI Contains All Commands", test_cli_contains_all_commands),
        ("Workflow Collect with Profiles", test_workflow_collect_data_with_profiles),
        ("Workflow Collect without Cache", test_workflow_collect_data_without_cache),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, True, None))
            print(f"✓ {test_name} PASSED")
        except AssertionError as e:
            results.append((test_name, False, str(e)))
            print(f"✗ {test_name} FAILED: {e}")
        except Exception as e:
            results.append((test_name, False, str(e)))
            print(f"✗ {test_name} ERROR: {e}")

    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)

    for test_name, result, error in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
        if error:
            print(f"       {error[:80]}")

    passed = sum(1 for _, r, _ in results if r)
    total = len(results)
    print(f"\nTotal: {passed}/{total} tests passed")

    return all(r for _, r, _ in results)


if __name__ == "__main__":
    success = run_all_phase7_tests()
    sys.exit(0 if success else 1)
