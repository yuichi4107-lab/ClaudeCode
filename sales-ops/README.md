# Sales OS

営業自律実行システム。3軸（フリーランス/コンテンツ/法人アウトバウンド）の営業オペレーションを自動化する。Phase 1 では軸C（法人アウトバウンド）のMVPを実装。

## セットアップ
```bash
pip install -r requirements.txt
cp .env.example .env  # 値を埋める
python scripts/init_db.py
python scripts/gmail_oauth_setup.py  # 初回のみOAuth承認
```

## cron（VPS本番想定）
- 03:00 `scripts/run_list_builder.py`
- 03:30 `scripts/run_personalizer.py`
- 手動or朝セッション承認後 `scripts/run_send_approved.py`

## テスト
```bash
pytest tests/ -v
```
