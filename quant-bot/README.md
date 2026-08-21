# quant-bot — 検証済み戦略のシグナル通知・ペーパートレードシステム

作成: 2026-07-08 ／ Phase 2a（シグナル+通知+ペーパー記録。実発注はPhase 2bでIB API接続後）

## 要件定義

- **ゴール**: OOS検証済みの2戦略のシグナルを毎日自動生成し、Telegram通知＋ペーパー台帳記録を行う
- **スコープ**: ①RSI(2)平均回帰（SPY/QQQ）シグナルエンジン ②CMEベーシス＋ファンディング監視。実発注・資金移動は含まない
- **完了条件**: (1)RSI2シグナルが正しく判定される (2)ベーシス/ファンディングが日次算出される (3)Telegramに通知が届く (4)台帳CSVに記録される (5)VPS cronで毎日自動実行される (6)quality-checker 85点以上

## 戦略（検証結果: .company/projects/投資戦略100とゴトー日EA再現/round2/）

### ① RSI(2)平均回帰（主力）
- 対象: SPY / QQQ（実発注はCMEマイクロ先物 MES/MNQ か ETF現物を想定）
- 買い: 終値 > 200日SMA かつ RSI(2) < 10 → 引けで買い
- 決済: RSI(2) > 70 または 終値 > 前日高値 → 引けで決済
- OOS実績(2023-2026): SPY 年6.9%/PF2.57/勝率80%、QQQ 年8.7%/PF2.88/勝率86%（コスト5bp込み）

### ② CMEベーシス（ルートA・小規模）
- 構成: CMEマイクロBTC先物(MBT)ショート + 国内現物BTCロング（デルタニュートラル）
- 監視: 先物ベーシス年率換算・Binanceファンディング3日平均
- 稼働条件: ベーシス年率 ≥ 5% でエントリー検討通知、ファンディング3日平均 < 0 で警戒通知
- 期待: ネット年2〜4%（2023-2026実測ベース）

## 運用（VPS: yn-vps /opt/quant-bot）

- cron 06:15 JST: `run_daily.py rsi2`（米国市場クローズ後。シグナル判定・台帳更新・通知）
- cron 09:30 JST: `run_daily.py basis`（ベーシス・ファンディング監視）
- 状態: `state/positions.json`（ポジション）、`state/ledger.csv`（ペーパー台帳）
- 通知: シグナル発生時＋月曜の週次ハートビート。エラー時は必ず通知

## Phase 2b（実発注）に必要なオーナー側の準備

1. **IB証券（日本）口座開設** — MES/MNQ（RSI2用マイクロ指数先物）とMBT（ベーシス用マイクロBTC先物）。TWS/IB Gateway APIの有効化
2. **国内暗号資産口座のAPI** — GMOコイン等（現物BTC買い用、取引APIキー発行）
3. 税理士確認 — 暗号資産デリバティブの課税区分（総合課税の可能性）
4. 初期資金の決定 — 推奨: RSI2側はMES 1枚（証拠金約250万円相当の代替としてETF現物も可）、ベーシス側はMBT 1枚=0.1BTC（約100万円規模）から

## デプロイ

```bash
# ローカル(Drive)から
scp -r quant-bot yn-vps:/opt/
ssh yn-vps "cd /opt/quant-bot && pip3 install -r requirements.txt && bash deploy/setup_env.sh && bash deploy/install_cron.sh"
```
