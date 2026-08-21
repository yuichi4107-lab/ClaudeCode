# WIN5予想モデル — 設計仕様書（案B：win5独立 ＋ 既存JRAデータ流用）

- 作成日: 2026-06-06
- 対象プロジェクト: `keiba-unified/win5/`
- ステータス: 設計承認済み（実装計画 writing-plans へ移行予定）

---

## 1. 背景と現状把握

### 1.1 経緯
OneDrive上に作業途中のWIN5予想モデル
（`C:\Users\fcmdt\OneDrive\デスクトップ\ClaudeCode-claude-win-prediction-model-Izfwm\...\win5_predictor`）
が存在する。これを本番リポジトリ（`g:\マイドライブ\YNFactory-cc` 配下の `keiba-unified/win5/`）へ
正式に移し、続きを進める。あわせて「既存の競馬予想で使っている過去データを活用できないか」を実現する。

### 1.2 調査で判明した事実（設計の前提）
- **OneDrive版WIN5の実態**: コードは約7,700行・73テストで「完成」扱いだが、
  **実データ収集・実学習・実バックテストは未実施**。レポートのROI等はすべて「想定値」。
  実DB・学習済みモデルは存在せず、あるのはサンプルCSVと `win5_results_2026.csv`
  （2026年1〜5月の実WIN5払戻＋当選馬の単勝人気を手動転記したもの）。
  → 「箱（パイプライン）は完成、中身（データと検証）が空」の状態。
- **既にリポジトリ内にある資産**:
  - `keiba-unified/win5/` … OneDrive版とほぼ同一コードが既に移植済み（win5.db は89レースのみで未接続）。
  - `keiba-unified/jra/keiba_live.db` … **2021-01-05〜2026-03-28の17,457レース／
    240,330着順／36,392頭／395騎手／470調教師／207,585払戻**。本番JRA予想実績も蓄積。
    これがそのままWIN5学習データに使える（WIN5＝JRA5レースの1着当てのため）。
- **データ移植の成立性（確認済み）**:
  - jra `results` に `odds_win`・`popularity`・`finish_position` があり、
    win5 `race_results`（`odds`/`popularity`/`finish_position`）へ素直にマッピング可能。
    → **1着ラベルもEV計算用の勝オッズも揃う**。
  - races/horses/jockeys/trainers も対応付け可能。jra→win5 は ETL（スキーマ変換移植）で完結。
- **唯一のデータ欠落**: WIN5対象レースのメタ情報（毎週どの5レースがWIN5か＋払戻＋キャリーオーバー）。
  `win5/src/scraper/win5_target.py` が netkeiba の `top/win5.html?kaisai_date=YYYYMMDD` から取得する設計。
  2021〜2026の**約250日分だけの軽量スクレイプ**で済む（フルの50〜100時間スクレイプとは別物）。

### 1.3 既存JRAモデルを「そのまま」流用しない理由
jra本番モデル `lgbm_model.predict_proba` は **複勝圏内（top-3）確率**を返す設計（本番が三連複・三連単中心のため）。
WIN5は**1着確率**が必要なので、jraモデルはそのまま使えない。
→ 本プロジェクトでは win5 を独立に保ち、jra の**データのみ**を流用して1着確率モデルを自前で学習する（案B）。

---

## 2. ゴールと成功条件

### 2.1 ゴール
自分で買うためのWIN5判断ツール。既存JRA 5年データで学習・**厳密なOOS（学習期間外）バックテスト**し、
予算帯・購入頻度の推奨まで提示する。**実弾ROI重視**。

### 2.2 成功条件
1. 正直な期待値計算（**較正済み勝率 × 実オッズ − 投資**）。
2. ウォークフォワードで過学習を排した検証（学習期間外のWIN5イベントのみで評価）。
3. Kelly基準による資金管理。
4. **+EVが無ければ「買わない」を明示**できること（撤退判断も成果）。

---

## 3. 配置とリコンサイル（「こちらに移す」の答え）

- **正本 = `keiba-unified/win5/`**（既に本番リポジトリ内・`PYTHONPATH=. python -m win5.src.app.cli` で動く構成）。
  これが「作業ディレクトリをこちらに移す」の到達点。
- OneDrive版と keiba-unified版を **diff** し、新しい方／欠けている物を keiba-unified/win5 に吸収。
- 統合後、OneDrive版は `archive/` へ退避（削除せず保管）。

---

## 4. アーキテクチャ（5レイヤ・win5自己完結を維持）

```
[1] データ取込   jra/keiba_live.db ──ETL──▶ win5.db (races/race_results/horses/jockeys/trainers/odds)
[2] WIN5イベント win5_target スクレイプ(2021-2026の対象5R+払戻+CO) ──▶ win5_events  ※csvで突合
[3] 勝率モデル   win5 features → trainer(LightGBM, 1着ラベル) + walk-forward CV + 確率較正
[4] 買い目最適化 win5_combiner/budget_optimizer/expected_value(較正勝率×実オッズ−投資)
[5] 検証・運用   backtester(win5_events上のROI/的中/DD) + Kelly/bankroll + CLI予想出力
```

各レイヤの責務・依存・入出力:

| レイヤ | 何をするか | 入力 | 出力 | 既存資産 |
|---|---|---|---|---|
| [1] ETL | jra DBのスキーマをwin5 DBへ変換移植 | keiba_live.db | win5.db (races/results/odds…) | 新規グルー（要実装） |
| [2] イベント収集 | 対象5R・払戻・CO・的中票数を収集 | netkeiba win5.html / csv | win5_events | win5_target.py |
| [3] 勝率モデル | 1着確率を学習・較正 | win5.db features | 較正済みモデル(model_registry) | features/, trainer.py, hyperopt.py |
| [4] 最適化 | 予算制約下で買い目を期待値順に列挙 | 較正勝率×実オッズ | 買い目リスト | optimizer/ |
| [5] 検証・運用 | OOSバックテスト＋資金管理＋日次出力 | win5_events, モデル | ROIレポート, 予想 | analysis/, bankroll/, app/cli |

---

## 5. データフロー

1. **ETL**: jra→win5 へ races/results/odds を変換移植（初回フル＋以後は差分）。
   学習ラベル = `finish_position == 1`。
2. **WIN5イベント収集**: 約250日分の対象5R・払戻・CO・的中票数を取得 → win5_events。
   `win5_results_2026.csv`（2026年1〜5月）で突合・検算。
3. **学習**: 時系列分割（未来リーク防止）で1着確率モデル＋較正（Brier/LogLossで評価）。
4. **最適化**: 5レースの較正勝率を掛け合わせ、予算制約下で買い目を列挙し期待値順に並べる。
5. **バックテスト**: win5_events上で「もし買っていたら」のROI・的中率・最大DD・連続非的中を算出し、
   **予算帯／購入頻度の推奨**を提示。

### 5.1 スキーマ・マッピング（jra keiba_live.db → win5.db）

| win5.race_results | ← jra.results | 備考 |
|---|---|---|
| race_id | race_id | |
| horse_id / horse_number / post_position | horse_id / horse_number / post_position | |
| finish_position | finish_position | **==1 が学習ラベル** |
| odds | odds_win | **EV計算用の勝オッズ** |
| popularity | popularity | 人気ベースライン用 |
| jockey_id / trainer_id / weight_carried / horse_weight / last_3f / sex_age | 同名/分解 | sex_age は sex+age へ分解 |

| win5.races | ← jra.races | 備考 |
|---|---|---|
| race_id / race_date / race_number / distance | race_id / date / race_number / distance | |
| surface / track_condition / weather / num_runners | surface / track_condition / weather / head_count | |
| venue_code / venue_name | venue（コード変換要） | venue表記の正規化が必要 |
| race_class | class | クラスコード対応表が必要 |

> 注: オッズは確定オッズ（odds_win）を当面の代理とする。厳密な事前EVには直前オッズが望ましいが、
> 5年遡及では確定オッズが現実解。**この近似は既知の制約**としてレポートに明記する。

---

## 6. 過学習対策（案B最大のリスクへの保険）

案B（自前モデル）は jra の anti-overfit 基盤の恩恵を受けないため、以下を必須とする:

1. 学習は**ウォークフォワード（年単位ロール）**のみ採用。単純ランダムCVは禁止。
2. **確率較正必須**（CalibratedClassifierCV）。EVは較正後勝率で計算する。
3. バックテストは**学習期間外（OOS）のWIN5イベント**だけで評価する。
4. **人気ベースライン**（`win5/src/popularity` の人気のみモデル）を基準とし、
   機械学習が **OOSでベースラインを上回るか**を合格条件にする。
   上回らなければ素直に人気モデル採用、または撤退（買わない判断）。

---

## 7. フェーズ分割（各フェーズに中間成果物と合格基準）

| フェーズ | 内容 | 中間成果物 | 合格基準 |
|---|---|---|---|
| **P0** | リコンサイル＆ETL移植 | 2コピー統合＋win5.dbにjra 5年データ投入 | win5.db に2021-2026のraces/resultsが入り、件数がjra側と整合 |
| **P1** | WIN5イベント収集 | win5_events 2021-2026 充足 | csv突合一致（2026年1〜5月の払戻が完全一致） |
| **P2** | 勝率モデル | 較正済み1着確率モデル | OOSでBrier/LogLoss較正OK・**人気ベースライン超え** |
| **P3** | 最適化＋バックテスト | OOS ROI/DD/的中レポート | 予算帯／頻度の推奨を数値付きで提示できる |
| **P4** | 運用CLI | 日曜の予想出力 | 「買う／買わない」判断つきで買い目を出力できる |

- 各フェーズは前工程が合格するまで次へ進まない。
- 各フェーズは最大5回まで実行→チェックを繰り返す（CLAUDE.md 品質ループ準拠）。

---

## 8. スコープ外（YAGNI）

以下は初期スコープ外。検証で +EV が確認できてから検討する。
- Streamlitダッシュボードの本格運用
- 自動cron実行
- 通知連携（メール/Slack/Telegram）
- クラウド／VPSデプロイ

---

## 9. リスクと既知の制約

- **過学習リスク**: 案Bの構造的弱点。§6の対策で緩和。人気ベースライン超えを越えられない可能性あり
  （その場合の正しい結論は「機械学習不要 or 撤退」）。
- **オッズ近似**: 確定オッズを事前EVの代理に使う既知の制約（§5.1）。
- **WIN5の難度**: 的中率は本質的に極小・払戻はキャリーオーバーで高変動。
  少数イベント（5年で約250）での統計的有意性に限界。バックテストは点推定でなく分布で見る。
- **データ品質**: jra DBの欠損・表記ゆれ（venue/class）。ETL時に正規化・検算する。

---

## 10. 未解決事項（実装計画で詰める）

- venue コード変換表・race_class コード対応表の確定。
- WIN5イベントの「対象5R」確定方法（netkeiba archive の構造変化への耐性）。
- 較正手法の選択（Platt / Isotonic）と評価指標のしきい値。
- 予算最適化の探索空間（全列挙32kパターンの実用性 vs 上位絞り込み）。
