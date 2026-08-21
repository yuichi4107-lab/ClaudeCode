"""
ポートフォリオ設定読み込みヘルパー — 工程D成果物

概要:
    `results/fx_phase1/portfolio_config.json` を読み込み、
    FXRunner / position_sizing.py が使いやすい形式に変換する。

    工程E（バックテスト検証）・工程F（Forward Test）で使用する。

使い方:
    from src.backtest.portfolio_config_loader import (
        load_portfolio_config,
        build_fx_runner_params,
        get_circuit_breaker_config,
        list_portfolio_ids,
    )

    # ポートフォリオ設定読み込み
    portfolio = load_portfolio_config(
        config_path="results/fx_phase1/portfolio_config.json",
        portfolio_id="pattern_A_conservative",
    )

    # FXRunner用パラメータに変換
    for strategy_entry in portfolio["strategies"]:
        params = build_fx_runner_params(strategy_entry)
        runner = FXRunner(
            strategy_id=params["strategy_id"],
            symbol=params["symbol"],
            timeframe=params["timeframe"],
        )
        result = runner.run(params=params["params"])

    # サーキットブレーカー設定取得
    cb_config = get_circuit_breaker_config(portfolio)
    print(f"連敗閾値: {cb_config['consecutive_loss_limit']} 回")

設計方針:
    - FXRunnerのインターフェース（strategy_id / symbol / timeframe / params）に合わせる
    - position_sizing.calculate_lot_size() の引数に対応した risk_per_trade_pct を保持
    - CB設定は dict 形式で返し、FXRunner側でそのまま使えるようにする
    - エラーメッセージは日本語で、工程E実装者が即座に原因を特定できるように
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 型エイリアス
# ---------------------------------------------------------------------------

PortfolioConfig = Dict[str, Any]
StrategyEntry = Dict[str, Any]
FXRunnerParams = Dict[str, Any]
CBConfig = Dict[str, Any]


# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__),
    "../../results/fx_phase1/portfolio_config.json",
)

VALID_PORTFOLIO_IDS = [
    "pattern_A_conservative",
    "pattern_B_diversified",
    "pattern_C_aggressive",
]


# ---------------------------------------------------------------------------
# メイン関数
# ---------------------------------------------------------------------------


def load_portfolio_config(
    config_path: Optional[str] = None,
    portfolio_id: str = "pattern_A_conservative",
) -> PortfolioConfig:
    """
    portfolio_config.json を読み込み、指定パターンのポートフォリオ設定を返す。

    Args:
        config_path:  portfolio_config.json のファイルパス。
                      None の場合は DEFAULT_CONFIG_PATH を使用。
        portfolio_id: 取得するポートフォリオのID。
                      選択肢: "pattern_A_conservative" / "pattern_B_diversified" / "pattern_C_aggressive"

    Returns:
        PortfolioConfig: 指定パターンのポートフォリオ設定dict。
                         strategies / circuit_breakers / expected_monthly_return_pct 等を含む。

    Raises:
        FileNotFoundError: 設定ファイルが見つからない場合。
        KeyError: 指定したportfolio_idが存在しない場合。
        ValueError: JSONフォーマットが不正な場合。

    Examples:
        >>> portfolio = load_portfolio_config(portfolio_id="pattern_A_conservative")
        >>> len(portfolio["strategies"])
        5
        >>> portfolio["expected_monthly_return_pct"]
        10.2
    """
    path = config_path or DEFAULT_CONFIG_PATH

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"portfolio_config.json が見つかりません: {path}\n"
            f"工程Dの成果物が results/fx_phase1/portfolio_config.json に存在するか確認してください。"
        )

    with open(path, "r", encoding="utf-8") as f:
        try:
            raw_config = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"portfolio_config.json のJSON解析に失敗しました: {e}")

    # portfolios リストから指定IDのものを探す
    portfolios: List[PortfolioConfig] = raw_config.get("portfolios", [])
    if not portfolios:
        raise ValueError(
            "portfolio_config.json に 'portfolios' キーが存在しないか空です。"
        )

    portfolio_map: Dict[str, PortfolioConfig] = {
        p["portfolio_id"]: p for p in portfolios
    }

    if portfolio_id not in portfolio_map:
        available = list(portfolio_map.keys())
        raise KeyError(
            f"portfolio_id '{portfolio_id}' が見つかりません。\n"
            f"利用可能なID: {available}"
        )

    portfolio = portfolio_map[portfolio_id]

    # メタ情報をトップレベルから補完
    portfolio.setdefault("total_capital", raw_config.get("total_capital", 100000))
    portfolio.setdefault("leverage_limit", raw_config.get("leverage_limit", 25.0))
    portfolio.setdefault("portfolio_version", raw_config.get("portfolio_version", "1.0"))

    return portfolio


def build_fx_runner_params(strategy_entry: StrategyEntry) -> FXRunnerParams:
    """
    strategy エントリ (portfolio_config.json の strategies リストの1要素) を
    FXRunner.run() に渡す引数の形式に変換する。

    Args:
        strategy_entry: portfolio_config.json["portfolios"][n]["strategies"][m]

    Returns:
        FXRunnerParams: FXRunner初期化・run()に渡す引数を含むdict。
            {
                "strategy_id": str,       # FXRunner.__init__ 引数
                "symbol": str,            # FXRunner.__init__ 引数
                "timeframe": str,         # FXRunner.__init__ 引数
                "params": dict,           # FXRunner.run(params=...) 引数
                "risk_per_trade_pct": float,  # position_sizing.calculate_lot_size(risk_pct=...) 引数
                "capital_allocation_pct": int,  # ポートフォリオ内の配分比率（参照用）
                "lot_multiplier": float,  # ロット倍率（参照用）
            }

    Raises:
        KeyError: 必須キー (strategy_id / symbol / timeframe / params) が存在しない場合。

    Examples:
        >>> params = build_fx_runner_params(strategy_entry)
        >>> runner = FXRunner(
        ...     strategy_id=params["strategy_id"],
        ...     symbol=params["symbol"],
        ...     timeframe=params["timeframe"],
        ...     data_path=f"data/fx/ohlcv/{params['symbol']}_{params['timeframe']}.csv",
        ... )
        >>> result = runner.run(params=params["params"])
    """
    required_keys = ["strategy_id", "symbol", "timeframe", "params"]
    for key in required_keys:
        if key not in strategy_entry:
            raise KeyError(
                f"strategy_entry に必須キー '{key}' が存在しません。\n"
                f"portfolio_config.json の strategies エントリを確認してください。"
            )

    return {
        "strategy_id": strategy_entry["strategy_id"],
        "symbol": strategy_entry["symbol"].upper().replace("/", ""),
        "timeframe": strategy_entry["timeframe"],
        "params": strategy_entry["params"],
        "risk_per_trade_pct": strategy_entry.get("risk_per_trade_pct", 3.0),
        "capital_allocation_pct": strategy_entry.get("capital_allocation_pct", 20),
        "lot_multiplier": strategy_entry.get("lot_multiplier", 1.0),
        "allocation_reason": strategy_entry.get("allocation_reason", ""),
    }


def get_circuit_breaker_config(portfolio: PortfolioConfig) -> CBConfig:
    """
    ポートフォリオ設定からサーキットブレーカー設定を取り出す。

    portfolio_config.json の circuit_breakers キーを優先し、
    存在しない場合はデフォルト値（circuit_breaker_spec.md 推奨値）を返す。

    Args:
        portfolio: load_portfolio_config() が返すportfolio設定dict。

    Returns:
        CBConfig: サーキットブレーカー設定dict。
            {
                "consecutive_loss_limit": int,       # CB-1: 連敗閾値 N
                "monthly_dd_limit_pct": float,       # CB-2: 月次DD閾値（正値 %）
                "cumulative_dd_limit_pct": float,    # CB-3: 累積DD閾値（正値 %）
                "end_of_month_reduction_threshold_pct": float,  # CB-4: 月末縮小発動閾値（0=マイナスなら発動）
                "priority_order": str,               # 優先度説明
            }

    Examples:
        >>> cb = get_circuit_breaker_config(portfolio)
        >>> cb["consecutive_loss_limit"]
        5
        >>> cb["monthly_dd_limit_pct"]
        10.0
    """
    # デフォルト値（circuit_breaker_spec.md 推奨値）
    defaults: CBConfig = {
        "consecutive_loss_limit": 5,
        "monthly_dd_limit_pct": 10.0,
        "cumulative_dd_limit_pct": 25.0,
        "end_of_month_reduction_threshold_pct": 0,
        "priority_order": "CB3 > CB2 > CB4 > CB1",
    }

    cb_raw = portfolio.get("circuit_breakers", {})

    # キー名マッピング（portfolio_config.json の cb1_xxx 形式と circuit_breaker_spec.md の形式を統合）
    key_mapping = {
        "cb1_consecutive_loss_limit": "consecutive_loss_limit",
        "cb2_monthly_dd_limit_pct": "monthly_dd_limit_pct",
        "cb3_cumulative_dd_limit_pct": "cumulative_dd_limit_pct",
        "cb4_end_of_month_reduction_threshold_pct": "end_of_month_reduction_threshold_pct",
        # 短縮形も対応（circuit_breaker_spec.md の circuit_breaker キー形式）
        "consecutive_loss_limit": "consecutive_loss_limit",
        "monthly_dd_limit_pct": "monthly_dd_limit_pct",
        "cumulative_dd_limit_pct": "cumulative_dd_limit_pct",
        "end_of_month_reduction_threshold_pct": "end_of_month_reduction_threshold_pct",
    }

    result = dict(defaults)
    for raw_key, value in cb_raw.items():
        normalized_key = key_mapping.get(raw_key)
        if normalized_key:
            result[normalized_key] = value

    return result


def list_portfolio_ids(config_path: Optional[str] = None) -> List[str]:
    """
    portfolio_config.json に定義されているポートフォリオIDの一覧を返す。

    Args:
        config_path: portfolio_config.json のパス。None で DEFAULT_CONFIG_PATH。

    Returns:
        List[str]: ポートフォリオIDのリスト。

    Examples:
        >>> ids = list_portfolio_ids()
        >>> "pattern_A_conservative" in ids
        True
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return [p["portfolio_id"] for p in raw.get("portfolios", [])]


def get_portfolio_summary(config_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    全ポートフォリオパターンのサマリーを返す。

    Returns:
        List[Dict]: 各パターンの概要 (id / name / expected_monthly_return_pct / expected_max_dd_pct / lot_multiplier)

    Examples:
        >>> summaries = get_portfolio_summary()
        >>> for s in summaries:
        ...     print(f"{s['portfolio_id']}: 月利{s['expected_monthly_return_pct']}% DD{s['expected_max_dd_pct']}%")
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    summaries = []
    for p in raw.get("portfolios", []):
        summaries.append({
            "portfolio_id": p.get("portfolio_id", ""),
            "portfolio_name": p.get("portfolio_name", ""),
            "expected_monthly_return_pct": p.get("expected_monthly_return_pct", 0.0),
            "expected_max_dd_pct": p.get("expected_max_dd_pct", 0.0),
            "lot_multiplier": p.get("lot_multiplier", 1.0),
            "capital_allocation_total_pct": p.get("capital_allocation_total_pct", 0),
            "strategy_count": len(p.get("strategies", [])),
        })

    return summaries


# ---------------------------------------------------------------------------
# CLIエントリーポイント（確認用）
# ---------------------------------------------------------------------------


def _print_summary() -> None:
    """ポートフォリオサマリーを表示する（動作確認用）。"""
    summaries = get_portfolio_summary()

    print("=" * 70)
    print("  FX Phase1 ポートフォリオ設定サマリー")
    print("=" * 70)

    for s in summaries:
        print(f"\n  [{s['portfolio_id']}]")
        print(f"    名称         : {s['portfolio_name']}")
        print(f"    期待月利     : {s['expected_monthly_return_pct']:.2f}%")
        print(f"    想定MaxDD    : {s['expected_max_dd_pct']:.2f}%")
        print(f"    ロット倍率   : {s['lot_multiplier']:.1f}倍")
        print(f"    配分合計     : {s['capital_allocation_total_pct']}%")
        print(f"    戦略数       : {s['strategy_count']}戦略")

    print("\n" + "=" * 70)
    print("  使い方:")
    print("    from src.backtest.portfolio_config_loader import load_portfolio_config")
    print("    portfolio = load_portfolio_config(portfolio_id='pattern_A_conservative')")
    print("=" * 70)


if __name__ == "__main__":
    _print_summary()
