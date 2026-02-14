# JRA Win5 予想ソフト 実装計画

## Context
JRA Win5（毎週日曜の指定5レースの1着馬を全て的中させる馬券）の予想ソフトをPythonで新規作成する。Webスクレイピングでデータ収集し、LightGBMによる機械学習モデルで各レースの勝馬予測を行い、予算制約下で最適な買い目を自動生成する。

## 技術スタック
- **言語**: Python 3.10+
- **ML**: LightGBM, scikit-learn, Optuna(ハイパラ最適化), SHAP(特徴量分析)
- **データ**: pandas, numpy, SQLite
- **スクレイピング**: requests, BeautifulSoup4, lxml
- **可視化**: matplotlib, plotly
- **CLI**: click, rich, tqdm
- **ダッシュボード**: Streamlit（オプション）

## プロジェクト構成
```
D:\win5_predictor\
├── pyproject.toml
├── .gitignore
├── src/
│   ├── config/          # 設定・定数・競馬場コード
│   │   ├── settings.py
│   │   └── venues.py
│   ├── scraper/         # Webスクレイピング
│   │   ├── base.py          # 基底クラス(レート制限・キャッシュ)
│   │   ├── race_list.py     # レースID一覧取得
│   │   ├── race_result.py   # レース結果取得
│   │   ├── race_entry.py    # 出馬表取得
│   │   ├── horse_profile.py # 馬情報取得
│   │   ├── jockey_trainer.py# 騎手・調教師情報
│   │   ├── odds.py          # オッズ取得
│   │   ├── win5_target.py   # Win5対象レース特定
│   │   └── scheduler.py     # データ収集パイプライン
│   ├── database/        # SQLiteデータベース
│   │   ├── connection.py    # DB接続・マイグレーション
│   │   ├── models.py        # データクラス定義
│   │   ├── repository.py    # CRUD操作
│   │   └── migrations/      # SQLスキーマ
│   ├── features/        # 特徴量エンジニアリング
│   │   ├── builder.py       # 特徴量構築オーケストレータ
│   │   ├── horse_features.py    # 馬の特徴量(約30個)
│   │   ├── jockey_features.py   # 騎手・調教師(約15個)
│   │   ├── race_features.py     # レース特徴量(約10個)
│   │   ├── odds_features.py     # オッズ特徴量(約6個)
│   │   ├── pedigree_features.py # 血統特徴量(約8個)
│   │   └── interaction_features.py # 交互作用(約6個)
│   ├── model/           # 機械学習モデル
│   │   ├── trainer.py       # LightGBM学習(時系列CV)
│   │   ├── predictor.py     # 推論・勝率予測
│   │   ├── evaluation.py    # 評価指標・SHAP分析
│   │   ├── hyperopt.py      # Optuna最適化
│   │   └── registry.py      # モデルバージョン管理
│   ├── optimizer/       # Win5最適化
│   │   ├── win5_combiner.py     # 買い目組み合わせ生成
│   │   ├── budget_optimizer.py  # 予算制約下の最適選択
│   │   └── expected_value.py    # 期待値計算
│   ├── bankroll/        # 資金管理
│   │   ├── kelly.py         # Kelly基準(1/4 Kelly推奨)
│   │   ├── fixed_fraction.py# 固定比率法
│   │   └── tracker.py       # 資金推移記録
│   ├── analysis/        # 分析・バックテスト
│   │   ├── backtester.py    # 過去データシミュレーション
│   │   ├── roi_calculator.py# 回収率計算
│   │   ├── visualizer.py    # グラフ描画
│   │   └── report.py        # レポート生成
│   └── app/             # アプリケーション層
│       ├── cli.py           # CLIインターフェース
│       ├── workflow.py      # エンドツーエンドパイプライン
│       └── streamlit_app.py # Webダッシュボード
├── models/              # 学習済みモデル(.pkl)
├── data/                # DB・キャッシュ・エクスポート
├── notebooks/           # 分析用Jupyter
└── tests/               # テストコード
```

## データベーススキーマ (SQLite)
主要テーブル:
- **races**: レース情報(距離・馬場・クラス等)
- **race_results**: 各馬のレース結果(着順・タイム・上がり3F・オッズ等)
- **horses**: 馬マスタ(血統・通算成績)
- **jockeys**: 騎手マスタ
- **trainers**: 調教師マスタ
- **odds_history**: オッズ推移
- **win5_events**: Win5開催情報(対象レース・配当・キャリーオーバー)
- **win5_bets**: 購入記録
- **bankroll**: 資金推移
- **model_registry**: モデル管理
- **feature_cache**: 特徴量キャッシュ

## 特徴量 (約80-120個)
| グループ | 数 | 主要特徴量 |
|---------|-----|-----------|
| 馬の近走成績 | ~15 | 勝率(5走), 複勝率, 平均着順, 休養日数, 連勝数 |
| 馬のスピード | ~8 | スピード指数, 上がり3F平均, 距離ベストタイム |
| 馬の適性 | ~10 | 距離別勝率, 馬場別勝率, 競馬場別勝率, 馬場状態別 |
| 馬の状態 | ~5 | 馬体重, 増減, 最適体重偏差, 年齢 |
| 騎手 | ~10 | 勝率, 競馬場別, 距離別, 馬との相性 |
| 調教師 | ~8 | 勝率, 騎手との相性, 距離・馬場別 |
| レース | ~10 | 場の強さ, ペース予測, 脚質適合度, 枠順バイアス |
| オッズ | ~6 | 単勝オッズ, 暗示確率, 人気順, 対本命倍率 |
| 血統 | ~8 | 父系の馬場・距離別勝率 |

## 予測アルゴリズム
1. **LightGBM二値分類**: 各馬の勝利確率を予測(target: 1着=1, その他=0)
2. **時系列CV**: 未来データのリークを防ぐWalk-forward検証
3. **確率キャリブレーション**: レース内で合計≈1.0に正規化
4. **エッジ検出**: モデル予測確率 vs オッズ暗示確率の乖離を発見

## Win5最適化ロジック
- 5レース各々の予測確率から、予算制約下で最適な買い目を選定
- **予算最適化**: 全有効割当(n1×n2×n3×n4×n5 ≤ 予算÷100)を列挙し、的中確率を最大化する組み合わせを選択
- **期待値計算**: 的中確率 × 推定配当 - 購入金額
- **Kelly基準**: 資金管理に1/4 Kelly法を適用

## 実装順序

### Phase 1: 基盤構築
1. プロジェクト作成(pyproject.toml, ディレクトリ構造)
2. config/settings.py, venues.py
3. database/(connection.py, models.py, repository.py, migrations/)
→ 検証: DB作成・テストデータの読み書き

### Phase 2: データ収集
4. scraper/base.py (レート制限・キャッシュ)
5. scraper/race_list.py, race_result.py
6. scraper/horse_profile.py, jockey_trainer.py, odds.py
7. scraper/win5_target.py, scheduler.py
→ 検証: 既知の1レースをスクレイプし実際の結果と照合

### Phase 3: 特徴量エンジニアリング
8. features/horse_features.py
9. features/jockey_features.py, race_features.py
10. features/odds_features.py, pedigree_features.py
11. features/builder.py
→ 検証: 既知レースの特徴量を手計算値と照合

### Phase 4: 機械学習モデル
12. model/trainer.py (LightGBM + 時系列CV)
13. model/predictor.py, evaluation.py
14. model/hyperopt.py, registry.py
→ 検証: AUC > 0.65, キャリブレーション確認

### Phase 5: Win5最適化
15. optimizer/win5_combiner.py
16. optimizer/budget_optimizer.py, expected_value.py
→ 検証: 予算制約の遵守, 期待値計算の正確性

### Phase 6: 分析・資金管理
17. analysis/backtester.py, roi_calculator.py
18. analysis/visualizer.py, report.py
19. bankroll/kelly.py, fixed_fraction.py, tracker.py
→ 検証: 2023-2025のバックテスト実行

### Phase 7: アプリケーション
20. app/cli.py, workflow.py
21. app/streamlit_app.py
→ 検証: `win5 predict --date 2026-02-15 --budget 10000` の完全実行

## CLIコマンド
```bash
win5 collect --start 2020-01-01 --end 2025-12-31  # データ収集
win5 train --start 2020-01-01 --end 2024-12-31     # モデル学習
win5 predict --date 2026-02-15 --budget 10000       # Win5予想
win5 backtest --start 2023-01-01 --end 2025-12-31   # バックテスト
win5 status                                          # システム状態確認
win5 dashboard                                       # Streamlit起動
```

## 注意事項
- netkeiba.comのスクレイピングは1秒以上の間隔を空ける（利用規約遵守）
- 過去データの初回収集は50時間以上かかる見込み（バックグラウンド実行推奨）
- Win5の控除率は30%（回収率100%超は困難。エッジの発見が鍵）
- オッズを特徴量に含めるモデルと含めないモデルの2種類を作成推奨
