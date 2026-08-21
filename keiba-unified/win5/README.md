# WIN5予想モジュール

## 概要
JRA WIN5（5レース連続1着的中）の予想・買い目最適化・資金管理システム

## 機能
- netkeiba.comからデータ収集
- LightGBMによる勝馬確率予測 (80-120特徴量)
- 予算制約下での買い目最適化（全列挙・32kパターン）
- Kelly基準による資金管理
- バックテスト・ROI分析
- CLI + Streamlit ダッシュボード

## 使い方
```bash
cd keiba-unified
# データ収集
PYTHONPATH=. python -m win5.src.app.cli collect --start 2020-01-01 --end 2025-12-31
# モデル学習
PYTHONPATH=. python -m win5.src.app.cli train --start 2020-01-01 --end 2024-12-31
# WIN5予想
PYTHONPATH=. python -m win5.src.app.cli predict --date 2026-03-22 --budget 10000
# バックテスト
PYTHONPATH=. python -m win5.src.app.cli backtest --start 2023-01-01 --end 2025-12-31
# ダッシュボード
PYTHONPATH=. python -m win5.src.app.cli dashboard
```

## データ
- `data/win5.db` — WIN5イベント・レース・結果・購入記録DB
- `data/win5_results_2026.csv` — 2026年の実WIN5払戻（手動転記。突合検算の正解データ）

## データ基盤の構築（P0/P1）

既存JRAデータ（`../jra/data/keiba_live.db`）を流用して win5.db を構築する。
すべて `keiba-unified/win5/` をカレントにして実行（`PYTHONPATH=src`）。

```bash
# P0: JRAレースデータをwin5.dbへ移植（17k+レース / 240k+着順, 2021-2026）
PYTHONPATH=src python scripts/import_jra_data.py
python scripts/verify_import.py            # VERIFY OK を確認

# P1: WIN5対象イベント（対象5R＋払戻＋CO＋的中/発売票数）を収集
PYTHONPATH=src python scripts/collect_win5_events.py   # 2021-2026, 約326イベント
```

### スクレイピングの要点（再調査不要）
- WIN5結果の正しいURLは **`race.netkeiba.com/top/win5.html?date=YYYYMMDD`**（EUC-JP・静的HTML・JS不要）。
  `?kaisai_date=` は無視され最新週を返す／`?idx=N` は現在週専用。**使うのは `?date=`**。
- 開催日列挙は **`win5_results.html?year=YYYY`**（2011-2026）。
- 払戻金・発売金額は **万/億の和数字**（例 `188万5200円`=1,885,200）。`parse_japanese_yen` で処理。
- 対象5レースの `race_id`（12桁）は移植済み JRA データと同形式で**直接JOIN可能**。
- jra DBのテキストはUTF-8（移植に特殊デコード不要）。オッズは確定オッズを事前EVの代理に使う既知の制約あり。
- 2026年直近の一部 race_id は JRA DB 未収録で未連結（収集自体は成功・バックテストは2021-2025中心）。
