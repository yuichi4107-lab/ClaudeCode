# yntools セミナーデモ版 設計仕様書

- 作成日: 2026-05-04
- 対象リポジトリ: `yn-tools/`
- 関連: `tools.ynfactory.online`（本番、現状販売継続）

## 1. 目的

yntools を「Claude Code でこういうものが作れますよ」というセミナー教材として見せられる**デモ版**を立ち上げる。本番（販売）はそのまま継続。

## 2. ゴール / 完了条件

- `demo.ynfactory.online` にアクセスすると、本番と同じツール一覧が**ログイン不要・無料**で全機能触れる
- 料金・販売文言は表示されない
- 各ツールに「Claude Code で開発」バッジが付く
- 本番 `tools.ynfactory.online`（販売・課金）は完全に従来どおり動作（影響ゼロ）
- 本番に新ツールを追加すると、デモ版にも自動で乗る（コードベースが同一なため）

## 3. スコープ

### やる
- 同一リポジトリ・同一コードベースのまま、`DEMO_MODE` 環境変数で挙動を切り替えるハイブリッド方式
- 同じ ConoHa VPS 内に別 docker-compose ファイルでデモ用コンテナを起動
- Nginx で `demo.ynfactory.online` をデモコンテナへ proxy（Let's Encrypt 証明書付き）
- DEMO_MODE 時の挙動: 自動ゲストログイン / Stripe バイパス / 料金表記非表示 / 「Claude Code で開発」バッジ表示 / トップページ差し替え / DB 永続化を無効化（インメモリ／セッション中のみ）
- DNS・Nginx・docker-compose.demo.yml の整備

### やらない
- 本番コードの大規模リファクタ（DEMO_MODE 分岐の挿入のみ）
- 開発時間・プロンプト数などの数値表記（誇張回避のためバッジのみ）
- デモ版独自の新機能追加
- 別 VPS／別ホスティングへの分離
- 管理者機能のデモ提供

## 4. 全体構成

```
                 Nginx (ConoHa VPS)
                 ├─ tools.ynfactory.online ──→ yntools-prod   (DEMO_MODE=false, 既存)
                 └─ demo.ynfactory.online  ──→ yntools-demo   (DEMO_MODE=true, 新規)
                                                  ↑
                                  同一リポジトリから別 docker-compose でビルド
```

- リポジトリ: 1 本（`yn-tools/`）
- Docker イメージ: 同一 Dockerfile から `docker-compose.yml`（本番）と `docker-compose.demo.yml`（デモ）でそれぞれビルド
- DB: 本番は既存 SQLite/Postgres、デモはインメモリまたは tmpfs 上の使い捨て SQLite

## 5. DEMO_MODE で変わる挙動一覧

| 項目 | 本番 (DEMO_MODE=false) | デモ (DEMO_MODE=true) |
|---|---|---|
| ログイン／会員登録 | 必須 | 自動ゲストログイン（即入場） |
| Stripe 決済 | 有効 | 完全バイパス（全ツール「購入済み」扱い） |
| 料金表記 | サブスク¥2000 / 1ツール¥100 | 非表示 |
| 開発バッジ | 非表示 | 各ツールに「🤖 Claude Code で開発」バッジ |
| ツール処理結果の保存 | DB へ永続化 | 保存しない（ブラウザを閉じたら消える） |
| 管理者機能 | 有効 | 非表示 |
| ヘッダー文言 | 「YN Factory ツール集」 | 「Claude Code 開発デモ｜YN Factory」 |
| トップページ | 販売 LP | セミナー説明文（「これは全て Claude Code で作りました」） |

## 6. 実装ポイント

### 6.1 共通モジュール
- `DEMO_MODE` を読む共通ヘルパを 1 ファイル追加（例: `app/core/demo_mode.py` 相当）
- 既定値は `false`。本番 docker-compose は未設定のまま、デモ docker-compose で `DEMO_MODE=true` を渡す

### 6.2 認証
- 認証ミドルウェアの先頭で DEMO_MODE 判定
- true の場合、固定の「ゲストユーザー」セッションを自動付与（DB 不要、セッション or JWT で実現）
- ログイン／登録ページへのアクセスはトップへリダイレクト

### 6.3 課金 / Stripe
- 「このユーザーはこのツールを購入済みか？」を判定する関数で、DEMO_MODE なら常に True を返す
- Stripe Webhook ／ Checkout 関連エンドポイントは DEMO_MODE 時に 404 を返す（誤って外部から叩かれてもデモ DB に影響しない）

### 6.4 UI / テンプレート
- ヘッダー・ランディング・ダッシュボード・各ツールページのテンプレートで `DEMO_MODE` フラグを参照
- 料金表記を含むパーシャルを `{% if not DEMO_MODE %}` で囲う
- トップページは `DEMO_MODE` 専用テンプレートを別ファイルで用意し、ルーティングで切り替え
- 「Claude Code で開発」バッジは共通レイアウトの footer 付近、または各ツール画面の上部に小さく配置（誇張せず控えめに）

### 6.5 データ永続化
- DEMO_MODE 時は DB 接続文字列を `sqlite:///:memory:` または tmpfs 上の `/tmp/demo.db` に差し替え
- アップロード保存先も `/tmp` 配下に向け、コンテナ再起動で消える状態にする
- 本番 DB ファイル・本番 uploads ディレクトリはデモコンテナにマウントしない（事故防止）

## 7. デプロイ構成

### 7.1 DNS
- `demo.ynfactory.online` → ConoHa VPS の IP（A レコード）

### 7.2 Nginx
- `/etc/nginx/sites-available/demo.ynfactory.online` を新規作成
- `tools.ynfactory.online` の設定をコピーし、proxy_pass 先のポートをデモコンテナ用に変更
- `certbot --nginx -d demo.ynfactory.online` で証明書発行

### 7.3 docker-compose.demo.yml
- 同じ Dockerfile を使用
- コンテナ名: `yntools-demo`
- 公開ポート: 既存と被らないポート（例: `8081`）
- 環境変数: `DEMO_MODE=true`、`STRIPE_*` 未設定
- DB ボリュームは**マウントしない**（インメモリ or 使い捨て）
- 本番の `.env` は読み込まない（`env_file` を専用の `.env.demo` に分ける）

### 7.4 デプロイ手順
- 既存ルール（`up -d --build` 必須）に従う
- 例: `docker compose -f docker-compose.demo.yml up -d --build`
- 本番デプロイ手順は変更なし

## 8. リスクと対策

| リスク | 対策 |
|---|---|
| 本番 DB をデモコンテナが触ってしまう | `.env.demo` を分離、本番ボリュームをマウントしない、DEMO_MODE 時は接続文字列を強制差し替え |
| Stripe Webhook がデモに飛ぶ | Stripe ダッシュボード側の Webhook 宛先は `tools.ynfactory.online` のみ。デモ側は Webhook ルートを 404 化 |
| 本番で誤って DEMO_MODE=true が有効になる | docker-compose.yml 側に `DEMO_MODE=false` を明示、起動時に環境変数をログ出力して確認可能に |
| デモ版で重い処理を悪用される | レート制限を DEMO_MODE 時に厳しめに設定（任意・将来対応で可） |

## 9. 受け入れチェック

- [ ] `tools.ynfactory.online` が従来どおり動作（ログイン・課金・各ツール）
- [ ] `demo.ynfactory.online` がログイン不要で開ける
- [ ] デモ版に料金表記・販売文言が一切表示されない
- [ ] デモ版で全ツールが触れる（課金画面が出ない）
- [ ] 各ツールに「Claude Code で開発」バッジが表示される
- [ ] デモ版で生成・保存したデータがコンテナ再起動で消える
- [ ] HTTPS 証明書が `demo.ynfactory.online` に発行されている
- [ ] 本番 DB ファイル・本番 uploads がデモコンテナから参照不能

## 10. 次工程
本仕様書ユーザー承認後、`writing-plans` スキルで実装プランへ。
