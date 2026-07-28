# 帯広ばんえい競馬 単勝予想システム

LightGBMを使用した帯広ばんえい競馬の単勝予想AIシステムです。

## セットアップ

```bash
pip install -r requirements.txt
```

## 使い方

### 1. データ収集

地方競馬公式サイトからレース結果データをスクレイピングします。

```bash
python main.py scrape --start 2025-01-01 --end 2025-12-31
```

### 2. モデル学習

収集したデータから特徴量を生成し、LightGBMモデルを学習します。

```bash
python main.py train
```

### 3. レース予測

学習済みモデルで単勝予測を行います。

```bash
# 本日のレース
python main.py predict

# 日付指定
python main.py predict --date 2026-03-14
```

## 特徴量

ばんえい競馬特有の特徴量を使用しています：

| カテゴリ | 特徴量 |
|---------|--------|
| 馬の過去成績 | 勝率、複勝率、平均着順、ベストタイム等 |
| 騎手成績 | �率、複勝率 |
| 調教師成績 | 勝率、複勝率 |
| 重量 | 馬体重、負担重量、重量比率 |
| レース条件 | 距離、出走頭数、枠順、月 |

## プロジェクト構成

```
keiba-ai-system/
├── main.py                  # メインCLI
├── config/
│   └── settings.py          # 設定ファイル
├── src/
│   ├── scraper/
│   │   └── banei_scraper.py # スクレイパー
│   ├── features/
│   │   └── feature_engineering.py  # 特徴量生成
│   └── model/
│       └── predictor.py     # 予測モデル
├── data/
│   ├── raw/                 # 生データ
│   └── processed/           # 加工済みデータ
└── models/                  # 学習済みモデル
```
