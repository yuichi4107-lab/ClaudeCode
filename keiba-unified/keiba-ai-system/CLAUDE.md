# 帯広ばんえい競馬 単勝予想システム

## プロジェクト概要
LightGBMを使ったばんえい競馬の単勝予測システム。
地方競馬公式サイト(keiba.go.jp)からデータを収集し、機械学習で予測する。

## コマンド

```bash
# テスト実行
python -m pytest tests/ -v

# サンプルデータ生成（スクレイピングできない環境用）
PYTHONPATH=. python scripts/generate_sample_data.py

# モデル学習
PYTHONPATH=. python main.py train

# 予測（CSVデータから）
PYTHONPATH=. python main.py predict --date 2025-12-30 --from-csv

# 推奨馬券（1R〜12R全レース予想 + 購入レース選定）
PYTHONPATH=. python main.py recommend --date 2025-12-30 --from-csv

# バックテスト（回収率シミュレーション）
PYTHONPATH=. python main.py evaluate
PYTHONPATH=. python main.py evaluate --test-ratio 0.3

# データ収集（要外部接続）
PYTHONPATH=. python main.py scrape --start 2025-01-01 --end 2025-12-31
```

## ディレクトリ構成

- `main.py` - CLIエントリーポイント (scrape / train / predict / recommend / evaluate)
- `config/settings.py` - 全設定値
- `src/scraper/` - keiba.go.jpスクレイパー
- `src/features/` - 特徴量エンジニアリング
- `src/model/` - LightGBM予測モデル
- `scripts/` - ユーティリティスクリプト
- `tests/` - pytest テスト

## 開発ルール

- `PYTHONPATH=.` を付けて実行すること
- テストは `python -m pytest tests/ -v` で実行
- 帯広競馬場コード: `36`
