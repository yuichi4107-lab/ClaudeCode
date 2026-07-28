# FX戦略モジュール — 使い方ガイド

`src/backtest/strategies/` は、FX自動売買システムPhase 1で実装された5本の戦略モジュールを提供します。

---

## クイックスタート

```python
from src.backtest.strategies import load_strategy, list_strategies, generate_signals

# 利用可能な戦略を確認
print(list_strategies())
# ['bb_reversion', 'mtf_confluence', 'rsi_divergence', 'london_breakout', 'ha_trend']

# 戦略をロード
strategy = load_strategy("bb_reversion")

# シグナル生成
import pandas as pd
df = pd.read_csv("data/fx/ohlcv/USDJPY_1h.csv")
result_df = strategy.generate_signals(df, params={}, filters={"use_sma200": True})

# シグナル確認
print(result_df[result_df["signal"] != 0][["signal", "tp_price", "sl_price", "hold_bars"]])
```

---

## 共通インターフェース

全5戦略は共通の関数シグネチャを持ちます:

```python
def generate_signals(
    df: pd.DataFrame,          # OHLCV (timestamp, open, high, low, close, volume)
    params: Dict[str, Any],    # 戦略固有パラメータ（空dictでDEFAULT_PARAMS使用）
    filters: Dict[str, bool],  # フィルター有効/無効フラグ
) -> pd.DataFrame:
    """
    Returns: df に以下のカラムを追加して返す
        - signal    : 1=ロングエントリー, -1=ショートエントリー, 0=何もしない
        - tp_price  : 利確価格（絶対価格）
        - sl_price  : 損切り価格（絶対価格）
        - hold_bars : 最大保有期間（バー数）
    """
```

---

## ファイル構成

```
src/backtest/strategies/
├── __init__.py         # 戦略レジストリ（load_strategy, list_strategies等）
├── base.py             # 抽象基底クラス BaseStrategy、共通ユーティリティ
├── filters.py          # 共通フィルター群（SMA200, ATR, Session, Event）
├── bb_reversion.py     # 戦略1: BB Mean Reversion + Trend Filter
├── mtf_confluence.py   # 戦略2: Multi-Timeframe Confluence
├── rsi_divergence.py   # 戦略3: RSI Divergence + MACD Confirm
├── london_breakout.py  # 戦略4: London Breakout
├── ha_trend.py         # 戦略5: Heikin-Ashi Trend Following + EMA Filter
└── README.md           # このファイル
```

---

## 5戦略の概要

### 1. BB Mean Reversion (`bb_reversion`)

**ロジック**: ボリンジャーバンド(20, 2.0)の下限タッチでロング、上限タッチでショート。RSIで過売り/過買いを確認。

**主要パラメータ**:
- `bb_period` (int): BBの期間（デフォルト20）
- `bb_std` (float): BB標準偏差倍率（デフォルト2.0）
- `rsi_oversold` (float): ロング用RSI閾値（デフォルト40.0）
- `rsi_overbought` (float): ショート用RSI閾値（デフォルト60.0）
- `tp_pct` (float): 利確幅（デフォルト0.003 = 0.3%）
- `sl_pct` (float): 損切り幅（デフォルト0.005 = 0.5%）

**フィルター**: `use_sma200`, `use_atr`, `use_session`, `use_event`

**適切な時間足**: 1h, 4h（レンジ相場で特に有効）

---

### 2. Multi-Timeframe Confluence (`mtf_confluence`)

**ロジック**: 日足SMA(200)トレンド + 4h EMA(20)方向 + 1h RSI(14)の3時間足一致でエントリー。

**主要パラメータ**:
- `daily_sma_period` (int): 日足SMA期間（デフォルト200）
- `h4_ema_period` (int): 4h EMA期間（デフォルト20）
- `rsi_long_threshold` (float): ロング用RSI閾値（デフォルト50.0）
- `rr_ratio` (float): リスクリワード比（デフォルト2.0）
- `sl_pct` (float): SL幅（デフォルト0.005）

**フィルター**: `use_atr`, `use_session`, `use_event`

**注意**: 1h足データのみで動作するが、内部でリサンプリングにより疑似マルチタイムフレームを実現。本番では別途4h/1dデータを渡すことを推奨。

---

### 3. RSI Divergence + MACD Confirm (`rsi_divergence`)

**ロジック**: RSI(14)のブリッシュ/ベアリッシュダイバージェンスを検出し、MACDヒストグラムのゼロクロスでエントリー確認。

**主要パラメータ**:
- `rsi_period` (int): RSI期間（デフォルト14）
- `rsi_oversold` (float): ロング用RSI閾値（デフォルト30.0）
- `div_lookback` (int): ダイバージェンス検出の遡り期間（デフォルト30）
- `swing_order` (int): ピーク検出の近傍サイズ（デフォルト3）
- `tp_pct` / `sl_pct`: 利確/損切り幅

**依存ライブラリ**: `scipy.signal.argrelmin/argrelmax`（未インストール時は簡易実装にフォールバック）

**フィルター**: `use_sma200`, `use_atr`, `use_session`, `use_event`

---

### 4. London Breakout (`london_breakout`)

**ロジック**: 東京セッション（UTC 00:00〜07:00）の高値・安値レンジを確定。UTC 08:00（ロンドン開始）に上値を上抜けでロング、下値を下抜けでショート。

**主要パラメータ**:
- `tp_multiplier` (float): TP = レンジ幅 × tp_multiplier（デフォルト1.5）
- `min_range_pct` (float): 最小レンジ幅（デフォルト0.001 = 0.1%）
- `hold_bars` (int): 最大保有バー数（デフォルト8）
- `exclude_monday` (bool): 月曜除外フラグ（デフォルトTrue）

**必須**: 1h足データ（UTC基準のタイムスタンプ）

**フィルター**: `use_sma200`, `use_atr`, `use_event`

---

### 5. Heikin-Ashi Trend Following (`ha_trend`)

**ロジック**: Heikin-Ashi変換後の連続陽線/陰線（デフォルト3本以上）を確認。EMA(50)フィルターでトレンド方向を制限してエントリー。

**主要パラメータ**:
- `ema_period` (int): EMAフィルター期間（デフォルト50）
- `consecutive_bars` (int): 連続HA同色バー数（デフォルト3）
- `tp_pct` / `sl_pct`: 利確/損切り幅

**フィルター**: `use_ema`（最重要）, `use_atr`, `use_session`, `use_event`

**HA変換式（決定論的）**:
```
HA_Close = (Open + High + Low + Close) / 4
HA_Open[i] = (HA_Open[i-1] + HA_Close[i-1]) / 2
HA_High = max(High, HA_Open, HA_Close)
HA_Low  = min(Low, HA_Open, HA_Close)
```

---

## 共通フィルター

`filters.py` が提供する4種類のフィルター:

| フィルターキー | 説明 | 対象戦略 |
|--------------|------|---------|
| `use_sma200` | close > SMA(200)でロング許可、close < SMA(200)でショート許可 | BB, MTF, RSI, London |
| `use_atr` | ATR(14)が最小閾値〜最大閾値内のみエントリー | 全戦略 |
| `use_session` | ロンドン/NYセッション時間のみエントリー（東京セッション除外） | BB, MTF, RSI |
| `use_event` | FOMC/NFP/日銀発表前後をスキップ | 全戦略 |
| `use_ema` | close > EMA(50)でロング許可（HA Trend専用） | HA Trend |

---

## APIリファレンス

### `list_strategies() -> List[str]`
利用可能な戦略IDのリストを返す。

### `load_strategy(strategy_id: str) -> BaseStrategy`
戦略IDからインスタンスをロード。

### `generate_signals(strategy_id, df, params=None, filters=None) -> pd.DataFrame`
戦略IDを指定してシグナルを生成する簡易API。

### `get_default_params(strategy_id: str) -> Dict[str, Any]`
デフォルトパラメータを取得。

### `get_param_grid(strategy_id: str) -> Dict[str, list]`
工程4（グリッドサーチ）用のパラメータグリッドを取得。

---

## バックテスト実行

```python
from src.backtest.fx_runner import FXRunner

runner = FXRunner(
    strategy_id="bb_reversion",
    symbol="USDJPY",
    timeframe="1h",
    data_path="data/fx/ohlcv/USDJPY_1h.csv",
)

result = runner.run(
    params={"bb_period": 20, "bb_std": 2.0},
    filters={"use_sma200": True, "use_atr": True},
)

print(result["stats"])
runner.save_result(result, "results/fx_phase1/")
```

---

## 動作確認

```bash
python scripts/verify_strategies.py
```

---

## 工程4への引き継ぎ

- 各戦略の `PARAM_GRID` を `get_param_grid(strategy_id)` で取得可能
- 最適化評価関数は要件定義書の通り: `勝率×0.3 + PF×0.3 + 月利×0.3 + (1-DD/10)×0.1`
- DD > 10% の組み合わせはスコア=0（失格）
- `FXRunner.run()` を並列化して高速グリッドサーチを実装する
