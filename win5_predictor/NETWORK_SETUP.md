# ネットワーク設定（β較正データ収集のための allowlist）

β較正には netkeiba から「全頭オッズ＋着順」を収集する必要があるが、
Claude Code on the web の実行環境は**許可リスト型ネットワーク**で、既定では
netkeiba に到達できない（プロキシが `Host not in allowlist` で遮断）。

## 許可リストに追加するホスト

既存スクレイパー（`src/scraper/`）が使うのは以下:

| ホスト | 用途 | 参照 |
|--------|------|------|
| `db.netkeiba.com` | レース結果・レース一覧 | `NETKEIBA_BASE_URL` |
| `race.netkeiba.com` | 単勝オッズ | `NETKEIBA_RACE_URL` |

（必要に応じて `netkeiba.com` も追加）

## 手順

1. **環境のネットワークポリシーを変更**して上記ホストを許可リストに追加する。
   - これはセッション内（Claude）からは変更不可。環境設定で行う。
   - 参考: https://code.claude.com/docs/en/claude-code-on-the-web
2. **新しいセッションを開始**する（ポリシー変更は新しいコンテナにのみ反映）。
3. 新セッションで収集→較正を実行:
   ```bash
   cd win5_predictor
   pip install -r requirements.txt           # bs4 / lxml など
   python -m src.app.cli collect --start 2020-01-01 --end 2025-12-31  # 既存スクレイパー
   python build_history.py --db data/win5.db --out data/history.csv
   python run_calibrate.py data/history.csv   # → 推定 β
   python run_odds.py data/target_odds.csv --beta <推定値> --budget 10000
   ```

## 注意
- netkeiba は UA 必須・レート制限あり（`src/scraper/base.py` で対応済みのはず）。
- HTML 構造変更でパーサ修正が必要になる場合あり。到達可能になり次第、実データで検証する。
