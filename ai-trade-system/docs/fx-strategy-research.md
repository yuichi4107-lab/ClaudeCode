# FX戦略リサーチレポート — Phase 1 工程1成果物

**作成日**: 2026-04-12
**対象通貨ペア**: USD/JPY、EUR/JPY
**目標**: 勝率65%+、PF 1.8+、月利+2〜3%、DD 10%以下、月5トレード以上

---

## 1. エグゼクティブサマリー

### 選定戦略 5本

| # | 戦略名 | 期待勝率 | 期待PF | 実装難易度 | 月間トレード頻度 | 選定理由 |
|---|--------|----------|--------|------------|------------------|----------|
| 1 | **BB Mean Reversion + Trend Filter** | 60〜65% | 1.6〜2.0 | Low | 10〜20本/月 | 既存SMA50/200フィルターと直結。pandas_taで完結。USDJPY日足〜4hで実績 |
| 2 | **Multi-Timeframe Confluence (MTF)** | 65〜70% | 1.7〜2.2 | Mid | 5〜15本/月 | 日足トレンド + 4h/1hエントリーの組み合わせで勝率30-40%向上の実証あり |
| 3 | **RSI Divergence + MACD Confirm** | 60〜68% | 1.5〜1.9 | Mid | 5〜12本/月 | RSI単体55-65%がMACD併用で68〜76%まで改善。USDJPY中銀介入パターンとの相性良好 |
| 4 | **London Breakout** | 55〜62% | 1.5〜1.8 | Low | 15〜22本/月 | 明確なルール、自動化容易。ロンドン開始時刻フィルターで日本市場参加者に有利 |
| 5 | **Heikin-Ashi Trend Following + EMA Filter** | 60〜65% | 1.6〜2.0 | Low | 8〜15本/月 | EMA50フィルター追加でBTCバックテストで勝率62.7%、PF 1.81を実証。USDJPYのトレンド相場との親和性高 |

### 除外戦略と理由

| 戦略 | 除外理由 |
|------|---------|
| Pivot Point Bounce | 独立したバックテストで勝率30-35%のみ（65%目標に遠く及ばず）。電子取引時代では有効性が低下 |
| Fibonacci 61.8% Retracement | 100回テストで61.8%レベルへの価格反応は15%のみ。他レベルと有意差なく、信頼性なし（Trading Rush検証） |
| Engulfing Candle at S/R | FXではキャンドル系シグナルの有効性が株式より著しく低い（QuantifiedStrategies実証）。54/100の勝率 |
| Ichimoku (単体) | 包括的バックテスト（15,024トレード）で勝率41%、一部報告では10%。三役好転は遅行スパン遅延の問題あり |
| MACD Divergence (単体) | 発散パターンの定義が主観的。単体では52-65%と幅があり、後述のRSI Divergenceに吸収 |

---

## 2. 候補戦略の詳細調査

### 2.1 Bollinger Band Mean Reversion + Trend Filter

**ロジック**:
- BBバンド(20, 2.0)の下限タッチでロングエントリー
- 中線（20SMA）到達で利確
- 上位足（日足）のSMA200がuptrend時のみ有効
- RSI(14) < 40 で過売り確認

**期待勝率の根拠**:
- QuantifiedStrategies.com: MACD + Bollinger Bands組合せで**勝率78%、平均1.4%/trade**（commissions/slippage込み）
- 同サイト: レンジ相場でのBB下限bounce戦略は**60%超の勝率**
- tcl bollinger bands trader実装例: Dual-Deviation BB + RSI + Trend Filterで高確率リバーサル
- 注意: 株式市場ほど有効性高くない（FXはレンジ崩れが多い）。トレンドフィルター必須

**期待PF**: 1.6〜2.0（平均リワード/リスク = 1.5〜2.0）

**実装難易度**: Low
- `pandas_ta.bbands()` で計算可能
- `pandas_ta.rsi()` で過売り確認
- SMA200フィルターは既存 `trend_filter.py` 流用可能

**トレード頻度**: 月10〜20本（USDJPY 1h足でBBタッチは頻繁に発生）

**日本時間FX適用可否**: 適用可。ただしロンドン〜NYセッションのBBタッチがより有効（ボラ高い時間帯）

**フィルター追加案**:
- SMA200トレンドフィルター（既存）
- ATR(14)でボラティリティが低すぎる時は除外（スプレッド比率が悪化）
- NFP/FOMC前後24時間回避
- BB幅（Bandwidth）が異常に狭い時（squeeze）は除外

**参考文献**:
- QuantifiedStrategies.com, "MACD and Bollinger Bands Strategy – Rules, Setup, Backtest (78% Win Rate)" https://www.quantifiedstrategies.com/macd-and-bollinger-bands-strategy/
- QuantifiedStrategies.com, "Bollinger Bands Trading Strategy: Backtest" https://www.quantifiedstrategies.com/bollinger-bands-trading-strategy/
- TradeCodeLabs, "TCL Bollinger Bands Trader — Mean Reversion with Trend Filter" https://tradecodelabs.com/indicators/tcl-boll-bands-trader/

---

### 2.2 Multi-Timeframe Confluence (MTF)

**ロジック**:
- 日足: SMA200上位 → 上昇トレンド確認
- 4h足: 直近高値更新または押し目（20EMAバウンス）
- 1h足: RSI(14) > 50 かつ価格が4h足サポートに接触でエントリー
- SL: 4h足の直近安値の1pip下
- TP: 直近抵抗またはRR=2.0

**期待勝率の根拠**:
- Multiple timeframe analysis: 日足・4h・1hが全て一致した場合、**成功確率70〜80%**（SignalWavesAI/ACY研究）
- 単時間足比較で**30〜40%の勝率向上**（LiteFinance Multiple Timeframe Study）
- 実装例（backtesting.py公式ドキュメント）: マルチタイムフレームの技術的実装例あり

**期待PF**: 1.7〜2.2（RR=2以上を維持することで達成）

**実装難易度**: Mid
- 複数時間足データを並行処理する必要がある
- `pandas_ta` で各時間足のEMA/RSI/SMA計算は容易
- Saxo APIで1h + 4h + 1d データを取得済みであることが前提（工程2）
- シグナル生成時に3時間足分のデータをアライメントする処理が必要

**トレード頻度**: 月5〜15本（全時間足一致の条件が厳しいため、頻度は中程度）

**日本時間FX適用可否**: 適用可。日本時間外（ロンドン/NY）でもシグナルを検出。ただし東京時間（午前8〜17時JST）のシグナルは方向が不安定になりやすい

**フィルター追加案**:
- ATR(14)でボラが高い期間のみエントリー（低ボラ時のフェイクアウト防止）
- 3時間足一致必須（2/3一致では見送り）
- ロンドン/NYセッション時間内のみエントリー（日本時間は見送り）
- FOMC・NFP・日銀政策決定会合の前後48時間回避

**参考文献**:
- SignalWavesAI, "Multi-Timeframe Analysis: Complete Trading Guide 2025" https://signalwavesai.com/articles/multi-timeframe-analysis
- LiteFinance, "Technical Analysis Using Multiple Timeframes" https://www.litefinance.org/blog/for-beginners/technical-analysis/multiple-time-frame-analysis/
- ACY, "Swing Trader's Toolkit: Multi-Timeframe & Institutional Confluence" https://acy.com/en/market-news/education/swing-trader-toolkit-j-o-20251010-091542/
- backtesting.py公式, "Multiple Time Frames Example" https://kernc.github.io/backtesting.py/doc/examples/Multiple%20Time%20Frames.html

---

### 2.3 RSI Divergence + MACD Confirm

**ロジック**:
- RSI(14)のブリッシュダイバージェンス（価格が安値更新、RSIは安値切り上げ）を検出
- MACDヒストグラムが負→正に転換で確認（同タイムバー以内）
- エントリー: ダイバージェンス確認バーの終値
- SL: 直近安値の下
- TP: 直近抵抗またはRR=1.5

**期待勝率の根拠**:
- ForexBee.co: RSIダイバージェンス単体で**86%勝率（8/8件）**（但しサンプル少、参考値）
- QuantifiedStrategies.com: RSI + MACD組合せで**73%勝率（235トレード）**
- FibAlgo研究: RSIダイバージェンスはFear相場（急落後）で特に有効
- USDJPY固有: 中銀介入による急騰後の調整でRSIダイバージェンスが形成されやすい（市場特性）

**期待PF**: 1.5〜1.9（RR=1.5で勝率68%以上なら達成）

**実装難易度**: Mid
- RSIダイバージェンス検出: ピーク/トラフ検出アルゴリズムが必要（scipy.signal.argrelmin等）
- MACDゼロクロス: `pandas_ta.macd()` で計算後、ヒストグラム符号変化を検出
- ダイバージェンスのバー数制限（例: 最大30バー以内）の実装が必要

**トレード頻度**: 月5〜12本（ダイバージェンスは頻繁ではないが、USDJPY 1h足なら十分な頻度）

**日本時間FX適用可否**: 適用可。ただし東京時間の薄商いでダイバージェンスが多発するため、ロンドン/NYセッションへの制限を推奨

**フィルター追加案**:
- SMA200フィルター（下落トレンド中のブリッシュダイバージェンスは成立率低下）
- ダイバージェンスのバー数制限（20バー以内）
- RSI最大値の制限（RSIが30以下の深い過売り水準でのみ有効）
- 経済指標発表前後24時間回避

**参考文献**:
- QuantifiedStrategies.com, "MACD and RSI Strategy: 73% Win Rate" https://www.quantifiedstrategies.com/macd-and-rsi-strategy/
- ForexBee.co, "RSI Divergence Indicator Guide — 86% Winning Ratio" https://forexbee.co/rsi-divergence-indicator-guide/
- FibAlgo, "RSI Divergence Trading Strategy — Fear Markets" https://fibalgo.com/education/rsi-divergence-trading-strategy-fear-market
- QuantifiedStrategies.com, "USDJPY Forex Trading Strategy" https://www.quantifiedstrategies.com/usdjpy-forex-trading-strategy/

---

### 2.4 London Breakout

**ロジック**:
- 東京セッション（JST 9:00〜16:00 / UTC 0:00〜7:00）のレンジ（高値・安値）を記録
- ロンドン開始（UTC 8:00 / JST 17:00）にレンジ上限を上抜けでロング、下限を下抜けでショート
- SL: レンジ反対端
- TP: レンジ幅の1.5〜2倍
- フィルター: 日足SMAトレンドと同方向のブレイクのみ採用

**期待勝率の根拠**:
- QuantifiedStrategies.com: London Breakout戦略のPFは**1.5以上（RR=1.5時）**
- ロンドンセッション前後の経験則: セッション選択的スキップ（週1〜2日）で**勝率10〜15%向上**（経験則、DailyForex）
- ロンドン時間のFXボリューム: 全日取引量の約35%。USDJPYにとって最大ボラティリティ帯
- 追加根拠: ロンドン開始時刻の方向性継続は統計的に意味があり、特にEUR/JPYで効果的

**期待PF**: 1.5〜1.8（RR=1.5設定時。トレンドフィルター追加で改善余地あり）

**実装難易度**: Low
- 時刻フィルター: pandas datetime + UTC変換で実装容易
- レンジ計算: 東京セッション時間帯のhigh/low検出
- 最もシンプルで完全自動化しやすい戦略

**トレード頻度**: 月15〜22本（毎週5日 × 1シグナル/日 × フィルターで約70〜80%の日は有効）

**日本時間FX適用可否**: 最も適用しやすい。日本（JST）時間17時がエントリーポイントのため監視も容易

**フィルター追加案**:
- 日足SMAトレンドフィルター（最重要。逆方向ブレイクは見送り）
- 月曜日（週初め）のみ除外（ギャップが多い）
- ATR(14)でレンジが異常に小さい日（スプレッド比率悪化）は除外
- NFP/FOMC/日銀発表の週のロンドン月曜は除外

**参考文献**:
- QuantifiedStrategies.com, "London Breakout Strategy: Rules and Backtest Performance" https://www.quantifiedstrategies.com/london-breakout-strategy/
- DailyForex, "London Breakout Strategy — What it is & How to Trade it" https://www.dailyforex.com/forex-articles/london-breakout-strategy/210474
- DuhaniCapital, "Master the London Breakout Trading Strategy" https://duhanicapital.com/blogs/master-the-london-breakout-trading-strategy-for-consistent-forex-success

---

### 2.5 Heikin-Ashi Trend Following + EMA Filter

**ロジック**:
- Heikin-Ashi(HA)ローソク足を計算（OHLC→HA変換）
- HA色（陽線/陰線）の連続3本以上で方向確認
- 価格がEMA(50)より上（ロング）または下（ショート）でエントリー
- HAの色変化でエグジット（トレール的）
- SL: エントリー前のスイングHigh/Low

**期待勝率の根拠**:
- AAPL株バックテスト: EMA(50)フィルター追加で**勝率62.7%、PF 1.81**（QuantVPS, Heikin Ashi Strategy Guide）
- USDJPYはHA戦略の適切候補として明示（トレンドが明確なペア）
- QuantifiedStrategies.com: HA戦略は最大DDを29.89%→52.56%（buy-and-hold比）に削減効果あり
- EMAフィルター有無の差: 勝率が約20%pt向上（QuantVPS実証）

**期待PF**: 1.6〜2.0（トレンドが持続する環境では特に高い）

**実装難易度**: Low
- HA変換: 数式が固定（HA_Close = (O+H+L+C)/4、HA_Open = 前バーの(HA_O+HA_C)/2）
- pandasで完全計算可能
- EMAフィルター: `pandas_ta.ema()`

**トレード頻度**: 月8〜15本（HA色変化はBB等より少ないが、トレンド相場でまとまった利益を狙う）

**日本時間FX適用可否**: 適用可。USDJPYの中長期トレンド（円安・円高サイクル）との相性が良い

**フィルター追加案**:
- EMA(50)フィルター（必須。単体HAより勝率20%pt向上）
- ATR(14)ボラティリティフィルター（低ボラ時はHA反転が多発）
- 上位足（日足）トレンドとの一致確認

**参考文献**:
- QuantVPS, "Heikin Ashi Strategy for Trend Trading: A Complete Guide" https://www.quantvps.com/blog/heikin-ashi-strategy-for-trend-trading
- QuantifiedStrategies.com, "Heikin Ashi Trading Strategy (Backtest, Settings & Trading Rules)" https://www.quantifiedstrategies.com/heikin-ashi-trading-strategy/
- AsiaForexMentor, "Heiken Ashi Trading Strategy Review" https://www.asiaforexmentor.com/heiken-ashi-trading-strategy/

---

### 2.6〜2.10 除外候補の評価（参考）

| 戦略 | 評価結果 | 主要な根拠 |
|------|---------|-----------|
| **Pivot Point Bounce** | 不採用 | 独立バックテスト勝率30-35%（QuantifiedStrategies "none generated reliable gains"）。電子取引時代では機能低下 |
| **Fibonacci 61.8% Retracement** | 不採用 | Trading Rush 100回テスト: 61.8%レベルでの反応は全レベルと有意差なし。「statisticsが等価」＝フィボナッチ固有の優位性が否定 |
| **Engulfing Candle at S/R** | 不採用 | FXでは株式より有効性低い（QuantifiedStrategies実証）。100回中54回のみ上昇（ランダムと近い）。スプレッドコストで優位性消滅 |
| **Ichimoku (三役好転)** | 不採用（単体） | LiberatedStockTrader 15,024トレード: 勝率10〜41%とブレが大。遅行スパン26期間遅延でエントリーが遅れる |
| **MACD Divergence (単体)** | 不採用（RSI/MACDに吸収） | 52〜81%と測定値の幅が大きく独立評価困難。戦略2.3 (RSI Div + MACD Confirm) として実装 |

---

## 3. フィルター施策の網羅リストと効果検証根拠

### 3.1 トレンドフィルター

| フィルター | 実装方法 | 効果の根拠 |
|-----------|----------|-----------|
| **SMA200フィルター** | `price > SMA(200)` でロングのみ許可 | 既存 `trend_filter.py` で実装済み。S&P500バックテスト: SMA200タイミングでDDを大幅削減（QuantifiedStrategies） |
| **SMA50/200クロス** | SMA(50) > SMA(200) でロング許可 | ゴールデンクロス/デッドクロスの定番フィルター。既存コードで実装済み |
| **EMA(50)フィルター** | `price > EMA(50)` でロングのみ | HA戦略で勝率20%pt向上（QuantVPS実証） |

**推奨**: SMA200をプライマリフィルター（既存コード流用）、EMA50をセカンダリフィルターとして各戦略に追加。

---

### 3.2 ボラティリティフィルター

| フィルター | 実装方法 | 効果の根拠 |
|-----------|----------|-----------|
| **ATR最小値フィルター** | `ATR(14) > threshold` でのみエントリー | 低ボラ時はスプレッドがATR比で拡大し、期待値がマイナスになる。ATRフィルターで低ボラ時の誤エントリーを除外（bestmt4ea.com実証） |
| **ATR最大値フィルター** | `ATR(14) < threshold_max` で急激な高ボラ時を除外 | 指標発表直後の急騰/急落でのフェイクアウト防止 |
| **Bollinger Width** | BBバンド幅が一定以下でsqueze状態 → 除外 | スクイーズ後のブレイクは方向不定。ブレイク方向確認まで待機 |

**推奨ATR計算**: `pandas_ta.atr(high, low, close, length=14)`
**USDJPY参考閾値（1h）**: ATR(14) > 0.10（10銭）、ATR(14) < 0.80（80銭）

---

### 3.3 時間帯フィルター

| フィルター | 時刻（UTC/JST） | 効果の根拠 |
|-----------|----------------|-----------|
| **ロンドンセッション優先** | UTC 8:00〜17:00（JST 17:00〜翌2:00） | 全FXボリュームの35%。BBタッチ、ブレイクアウトが最も信頼できる時間帯 |
| **NYセッション** | UTC 13:00〜22:00（JST 22:00〜翌7:00） | USDJPY流動性が高い。ロンドン/NYオーバーラップ（UTC 13-17時）が最高ボラ帯 |
| **東京セッション除外** | UTC 0:00〜7:00（JST 9:00〜16:00） | 薄商いで偽シグナル多発。ただしロンドンブレイクアウトの「レンジ形成」期間として活用 |
| **週末明け月曜午前回避** | 月曜UTC 0:00〜7:00 | 週末ギャップにより東京時間の価格動作が不安定 |

**根拠**: ロンドンセッション選択的スキップで勝率10-15%向上（DailyForex経験則）。BabyPips公式セッション分析でロンドン>NY>東京のボリューム順が確認済み。

---

### 3.4 重要指標発表回避フィルター

| イベント | 回避期間（推奨） | 理由 |
|---------|----------------|------|
| **FOMC政策決定会合** | 発表前後48時間 | USDJPYへの影響が最大。2024年は200pip超の急動 |
| **NFP（米雇用統計）** | 発表前後24時間 | 毎月第1金曜。発表直後のスパイクで SL 多発 |
| **日銀政策決定会合** | 発表前後48時間 | JPY対全通貨に影響。YCC修正等で300pip超も |
| **CPI（米消費者物価）** | 発表前後24時間 | インフレ関連でFOMC予測が変動 |
| **GDP速報値** | 発表前後12時間 | 影響は中程度 |

**実装方針**: Pythonの `pandas_market_calendars` または固定カレンダーJSONで経済指標日程を管理。バックテスト時も適用して再現性を確保。

---

### 3.5 スプレッド拡大時間帯回避

| 時間帯 | 回避理由 |
|--------|---------|
| 日曜UTC 21:00〜月曜UTC 0:00 | 週初めオープンギャップでスプレッド拡大（3〜10pip） |
| 毎日UTC 21:45〜22:15 | NYクローズ〜東京オープンの移行期で流動性低下 |
| 米祝日（感謝祭等） | 米市場休場でFX流動性が半減 |

**実装**: UTC時刻チェックでエントリー禁止時間を設定。スプレッド情報はSaxo APIから取得可能。

---

## 4. 最終選定：実装候補5本と選定理由

### 比較マトリクス

| 評価軸 (配点) | BB Mean Rev | MTF Confluence | RSI Div+MACD | London Breakout | HA Trend |
|--------------|:-----------:|:--------------:|:------------:|:---------------:|:--------:|
| **勝率65%+見込み** (25) | 20 | 25 | 22 | 18 | 20 |
| **PF 1.8+見込み** (20) | 18 | 20 | 16 | 15 | 18 |
| **実装容易性** (20) | 20 | 14 | 14 | 20 | 20 |
| **月5本以上** (15) | 15 | 12 | 10 | 15 | 13 |
| **日本時間適用** (10) | 9 | 8 | 8 | 10 | 9 |
| **既存コード親和性** (10) | 10 | 9 | 8 | 9 | 9 |
| **合計** | **92** | **88** | **78** | **87** | **89** |

### 選定基準

以下の3基準を全て満たすものを採用:
1. 期待勝率の根拠が複数ソースで60%超（65%への改善余地あり）
2. pandas_taで実装完結（外部ML等不要）
3. 月5トレード以上が見込める

### 選定5本の最終理由

1. **BB Mean Reversion + Trend Filter**: 既存SMA50/200フィルター流用で開発コスト最小。MACD組合せ78%勝率の実証あり。
2. **MTF Confluence**: 3時間足一致で70-80%成功率の研究結果が最も高い期待値を示す。フラッグシップ戦略候補。
3. **RSI Divergence + MACD Confirm**: USDJPY固有の中銀介入後リバウンドと相性良。73%勝率（235トレード）の実証。
4. **London Breakout**: ルールが最も客観的で実装最短。日本居住者のJST生活時間と完全一致するシグナル発生時刻。
5. **HA Trend Following + EMA**: EMAフィルター追加で62.7%/PF 1.81実証。トレンド持続環境（円安相場等）で強い。

---

## 5. 各戦略のパラメータ空間設計（工程4 グリッドサーチ用）

### 5.1 BB Mean Reversion + Trend Filter

```python
param_grid = {
    "bb_period":       [15, 20, 25],           # BBバンド期間
    "bb_std":          [1.5, 2.0, 2.5],         # 標準偏差倍率
    "rsi_period":      [10, 14, 21],            # RSI期間
    "rsi_oversold":    [30, 35, 40],            # 過売り閾値
    "take_profit":     [0.002, 0.003, 0.005, 0.008],   # TP (0.2〜0.8%)
    "stop_loss":       [0.001, 0.002, 0.003, 0.005],   # SL (0.1〜0.5%)
    "hold_bars":       [5, 10, 15, 20],         # 最大保有バー数
    "use_filter":      [True, False],           # SMA200フィルター有無
}
# 推定組み合わせ数: 3×3×3×3×4×4×4×2 = 10,368
# 削減策: TP > SL の組み合わせのみ有効（約50%削減 → 約5,000通り）
```

### 5.2 Multi-Timeframe Confluence (MTF)

```python
param_grid = {
    "trend_tf":        ["1d"],                  # 固定（日足トレンド）
    "entry_tf":        ["4h", "1h"],            # エントリー時間足
    "sma_period":      [100, 150, 200],         # トレンド判定SMA
    "ema_period":      [20, 50],                # 押し目判定EMA
    "rsi_threshold":   [45, 50, 55],            # RSI最低値
    "take_profit":     [0.003, 0.005, 0.008, 0.010],  # TP
    "stop_loss":       [0.002, 0.003, 0.005],   # SL
    "hold_bars":       [5, 10, 20, 30],         # 最大保有バー
    "use_filter":      [True, False],
}
# 推定組み合わせ数: 1×2×3×2×3×4×3×4×2 = 3,456
```

### 5.3 RSI Divergence + MACD Confirm

```python
param_grid = {
    "rsi_period":      [10, 14, 21],            # RSI期間
    "macd_fast":       [8, 12],                 # MACD Fast
    "macd_slow":       [21, 26],                # MACD Slow
    "macd_signal":     [9],                     # MACDシグナル線
    "div_lookback":    [10, 20, 30],            # ダイバージェンス探索バー数
    "rsi_low_thresh":  [25, 30, 35],            # RSI最大安値閾値
    "take_profit":     [0.003, 0.005, 0.008],   # TP
    "stop_loss":       [0.002, 0.003, 0.005],   # SL
    "hold_bars":       [5, 10, 15],             # 最大保有バー
    "use_filter":      [True, False],
}
# 推定組み合わせ数: 3×2×2×1×3×3×3×3×3×2 = 3,888
```

### 5.4 London Breakout

```python
param_grid = {
    "tokyo_start_utc":  [0],                    # 固定: UTC 0:00
    "tokyo_end_utc":    [7],                    # 固定: UTC 7:00
    "london_entry_utc": [7, 8, 9],              # ロンドン開始エントリー時刻
    "range_buffer":     [0.0001, 0.0003, 0.0005], # ブレイク確認バッファ (pip)
    "take_profit_mult": [1.0, 1.5, 2.0, 2.5],  # レンジ幅の何倍でTP
    "stop_loss_mult":   [0.5, 0.75, 1.0],       # レンジ幅の何倍でSL
    "hold_bars":        [4, 8, 12, 16],         # 最大保有バー（1h基準）
    "use_filter":       [True, False],          # 日足トレンドフィルター
}
# 推定組み合わせ数: 1×1×3×3×4×3×4×2 = 864
```

### 5.5 Heikin-Ashi Trend Following + EMA Filter

```python
param_grid = {
    "ha_consecutive":  [2, 3, 4],              # HA同色連続本数でエントリー
    "ema_period":      [20, 50, 100],           # EMAフィルター期間
    "atr_period":      [10, 14],               # ATR計算期間
    "atr_sl_mult":     [1.0, 1.5, 2.0],        # SL = ATR × 倍率
    "take_profit":     [0.003, 0.005, 0.008, 0.010],  # TP
    "hold_bars":       [5, 10, 20, 30],        # 最大保有バー
    "use_filter":      [True, False],          # EMA上下フィルター
}
# 推定組み合わせ数: 3×3×2×3×4×4×2 = 1,728
```

---

## 6. 実装上の注意点

### 6.1 データ要件

| 戦略 | 必要時間足 | 最低期間 | 特記事項 |
|------|-----------|---------|---------|
| BB Mean Reversion | 1h, 4h | 2年分 | SMA200計算のため200本以上必須 |
| MTF Confluence | 1h + 4h + 1d | 2年分 | 3時間足のデータを同時取得・アライメント必要 |
| RSI Divergence | 1h, 4h | 2年分 | ダイバージェンスのlookback期間分のウォームアップが必要 |
| London Breakout | 1h | 2年分 | UTCタイムスタンプ必須（JSTへの変換不要） |
| HA Trend Following | 4h, 1d | 2年分 | HA変換のため前バーのデータが必要（初回バーは計算不可） |

### 6.2 計算コスト

| 処理 | コスト | 対策 |
|------|-------|------|
| MTF: 複数時間足アライメント | 中〜高 | `pd.merge_asof()` でダウンサンプル側を基準にマージ |
| RSI Divergence: ピーク検出 | 中 | `scipy.signal.argrelmin(order=5)` で高速化 |
| グリッドサーチ全組み合わせ | 高 | `concurrent.futures.ProcessPoolExecutor` で並列化 |
| HA変換 | 低 | pandasの累積演算で高速 |

### 6.3 FX固有の落とし穴

1. **スプレッドの扱い**: USDJPYは0.2pip（0.002円相当）、EURJPYは0.3pip。`fee_rate`としてUSJPY=0.00002、EURJPY=0.00003を設定（要件定義書M3項に準拠）

2. **FXボリュームはゼロ**: Saxo APIのFXデータはボリュームが0またはNaN。ボリュームフィルターを使う戦略は設計不可

3. **小数点精度**: 通貨レートは小数点4桁以上（例: 151.234）。整数変換は禁止

4. **土日ギャップ**: FX市場は土曜UTC 21時クローズ、日曜UTC 21時オープン。週次データに月曜始値のギャップが生じる。HA前バーをギャップ前の金曜で取得する

5. **日銀介入リスク**: 2024年のYCC修正・口頭介入でUSDJPYが10〜20円/日単位で動いた例あり。バックテスト期間（2024-09〜2026-04）には複数の介入イベントが含まれる。過去の介入日をフィルター対象として検討

6. **Saxo Chart API**: 工程2の`fetch_fx_ohlcv.py`が完了している前提。1hデータは約17,500本が必要（ページネーション15回以上）

7. **pandas_ta互換性**: `pandas_ta.bbands()`, `pandas_ta.rsi()`, `pandas_ta.macd()`, `pandas_ta.ema()`, `pandas_ta.atr()` がすべて `requirements.txt` に含まれていることを確認

### 6.4 既存コードとの住み分け

| 対象 | 扱い方針 |
|------|---------|
| `src/backtest/runner.py` | 変更禁止（Gemini Vision方式を維持）。新戦略は `src/backtest/fx_runner.py` に分離 |
| `src/signal/trend_filter.py` | 既存の `check_trend_filter()` を新戦略から `import` して流用 |
| `strategy_config.json` | 工程7まで変更しない。工程3では各戦略モジュールのデフォルトパラメータを別途 `fx_strategy_params.json` で管理 |

---

## 7. 参考文献・URLリスト

### 主要バックテスト研究

| 出典 | 内容 | URL | 信頼性評価 |
|------|------|-----|-----------|
| QuantifiedStrategies.com | MACD+BB: 78%勝率（実データバックテスト） | https://www.quantifiedstrategies.com/macd-and-bollinger-bands-strategy/ | 高（定量的、設定値公開） |
| QuantifiedStrategies.com | MACD+RSI: 73%勝率（235トレード） | https://www.quantifiedstrategies.com/macd-and-rsi-strategy/ | 高（サンプル数多） |
| QuantifiedStrategies.com | London Breakout: PF 1.5+（RR=1.5） | https://www.quantifiedstrategies.com/london-breakout-strategy/ | 高 |
| QuantifiedStrategies.com | USDJPY戦略バックテスト | https://www.quantifiedstrategies.com/usdjpy-forex-trading-strategy/ | 高 |
| QuantifiedStrategies.com | EURJPY戦略バックテスト | https://www.quantifiedstrategies.com/eurjpy-trading-strategy/ | 高 |
| LiberatedStockTrader | Ichimoku 15,024トレード検証 | https://www.liberatedstocktrader.com/ichimoku-cloud/ | 中〜高（大サンプル） |
| QuantVPS | HA + EMA(50): 62.7%勝率、PF 1.81 | https://www.quantvps.com/blog/heikin-ashi-strategy-for-trend-trading | 中（特定銘柄） |
| Trading Rush | Fibonacci 100回テスト結果 | https://tradingrush.net/i-tested-fibonacci-trading-strategy-100-times-to-find-the-truth-about-fibonacci-retracements/ | 中（YouTuber研究） |
| Trading Rush | Bullish Engulfing 100回テスト | https://tradingrush.net/bullish-engulfing-pattern-tested-100-times-so-you-can-master-your-candlestick-trading-strategy/ | 中 |
| ForexBee.co | RSI Divergence 86%勝率（8トレード） | https://forexbee.co/rsi-divergence-indicator-guide/ | 低（サンプル小） |
| FibAlgo | RSI Divergence Fear相場での有効性 | https://fibalgo.com/education/rsi-divergence-trading-strategy-fear-market | 中 |

### 戦略解説・教育ソース

| 出典 | 内容 | URL |
|------|------|-----|
| SignalWavesAI | MTF分析: 3時間足一致で70-80%成功率 | https://signalwavesai.com/articles/multi-timeframe-analysis |
| LiteFinance | 複数時間足分析: 勝率30-40%向上 | https://www.litefinance.org/blog/for-beginners/technical-analysis/multiple-time-frame-analysis/ |
| DailyForex | London Breakout: セッションスキップで10-15%向上 | https://www.dailyforex.com/forex-articles/london-breakout-strategy/210474 |
| BabyPips | FXセッション別特性 | https://www.babypips.com/learn/forex/forex-trading-sessions |
| FXCC | London Breakout包括ガイド | https://www.fxcc.com/london-breakout-strategy |
| bestmt4ea.com | ATRフィルター実装ガイド | https://bestmt4ea.com/atr-filter-strategy-free-download-powerful-yet-risky-guide-9-practical-rules/ |
| backtesting.py公式 | マルチタイムフレーム実装例 | https://kernc.github.io/backtesting.py/doc/examples/Multiple%20Time%20Frames.html |

### 参考文献の信頼性評価（総括）

- **高信頼**: QuantifiedStrategies.com（再現可能なコードとルール公開、定量的データ）
- **中信頼**: QuantVPS、LiberatedStockTrader、SignalWavesAI、LiteFinance（教育ベンチマーク）
- **低信頼（参考のみ）**: ForexBee.co（サンプル数8のみ）、一部YouTuber検証（再現性不明）

---

## 8. 工程3実装への引き継ぎ事項

### 実装優先順位

1. **London Breakout** — 最もシンプル。動作確認として最初に実装
2. **BB Mean Reversion + Trend Filter** — 既存コード流用最大
3. **HA Trend Following + EMA** — 実装容易、単体でPF 1.81実証あり
4. **MTF Confluence** — 複数時間足アライメントの実装が最も複雑（最後に実装）
5. **RSI Divergence + MACD Confirm** — ダイバージェンス検出アルゴリズムに注意

### generate_signals() インターフェース仕様（工程3実装用）

```python
def generate_signals(df: pd.DataFrame, **params) -> pd.Series:
    """
    シグナルを生成する。

    Args:
        df: OHLCVデータ（columns: open, high, low, close, volume）
            indexはpd.DatetimeIndex（UTC）であること
        **params: 戦略パラメータ（各戦略の param_grid から選択）
            use_filter: bool — フィルター有無の切り替え（必須）

    Returns:
        pd.Series: シグナル（1=ロング、-1=ショート、0=なし）
            indexはdfと同一
    """
```

### データスキーマ（工程2から引き継ぎ）

```
columns: ['timestamp', 'open', 'high', 'low', 'close', 'volume']
index: pd.DatetimeIndex（UTC）
dtypes: float64（全OHLCV列）
ファイルパス: data/fx/ohlcv/{USDJPY|EURJPY}_{1h|4h|1d}.csv
```

### フィルター設定（工程3実装用デフォルト値）

```python
# USDJPYデフォルト
DEFAULT_FILTERS_USDJPY = {
    "sma200_filter": True,
    "atr_min": 0.10,           # ATR(14) > 0.10円（10銭）
    "atr_max": 0.80,           # ATR(14) < 0.80円（80銭）
    "session_filter": ["london", "newyork"],  # 東京セッション除外
    "avoid_fomc": True,
    "avoid_nfp": True,
    "avoid_boj": True,
}

# fee_rate（スプレッド込みコスト）
FEE_RATE_USDJPY = 0.00002  # 0.2pip相当
FEE_RATE_EURJPY = 0.00003  # 0.3pip相当
```

---

*本ドキュメントは FX Phase 1 工程1の成果物。工程3 executor に引き渡す。*
*工程2（データ取得）と並行実施のため、工程3着手前に工程2の完了を確認すること。*
