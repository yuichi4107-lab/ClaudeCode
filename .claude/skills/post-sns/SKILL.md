---
name: post-sns
description: SNS（X / Instagram / Facebook / Threads）へ投稿する。テキスト・画像を指定して各プラットフォームに最適化した内容を投稿。対象SNSの指定も可能。ユーザーが単発でSNS投稿したい時に使う（shorts-factoryの自動生成動画投稿はshorts-factory-opsを使う）。
---

# SNS投稿スキル (post-sns)

## 概要

指定されたテキストや画像をSNSに投稿する。投稿先の指定がなければ全対応SNSに一括投稿する。各SNSの制約に合わせてコンテンツを自動調整する。

## 入力

- **投稿内容**（必須）: 投稿したいテキスト。テーマやキーワードだけでもOK。
- **画像パス**（任意）: 添付する画像ファイルのパス
- **投稿先**（任意）: `x` / `instagram` / `facebook` / `threads` / `all`（デフォルト: 対応済みの全SNS）

## 各SNSの制約

| SNS | テキスト上限 | 画像 | 備考 |
|-----|------------|------|------|
| X | 280文字 | 任意 | URLは23文字換算 |
| Instagram | 2,200文字 | 必須 | テキストのみ投稿不可 |
| Facebook | 63,206文字 | 任意 | |
| Threads | 500文字 | 任意 | |

## ワークフロー

### Step 1: コンテンツ準備

ユーザーの投稿内容を各SNS向けに調整する。

- ユーザーがテーマやキーワードだけ指定した場合は、投稿文を作成する
- 各SNSの文字数制限に合わせてバリエーションを作成する
- ハッシュタグを適切に付与する
- 投稿先が指定されていない場合は、対応済みの全SNSを対象とする

調整後の投稿内容をユーザーに確認してから投稿する。上位 `note` runから呼び出された場合は、この汎用コマンドではなく、runの事前確認・承認・claim・結果照合を強制する `tools/note-sales-team/x_publish_worker.py` を使う。

### Step 2: X に投稿

dry-run（投稿しない検証）:

```bash
cd YNFactory-cc
python scripts/post_to_x.py "投稿テキスト" --dry-run
```

本番投稿（直前承認後のみ）：

```bash
cd YNFactory-cc
python scripts/post_to_x.py "投稿テキスト" --publish-approved
```

画像付きの場合：

```bash
python scripts/post_to_x.py "投稿テキスト" --image "画像パス" --publish-approved
```

本文への1件目リプ（直前承認後のみ）：

```bash
python scripts/post_to_x.py "リプ本文" --reply-to "本文のTweet ID" --publish-approved
```

投稿成功したらURLを記録する。タイムアウト等で結果が不明な場合は自動再投稿せず、アカウントの公開タイムラインを照合する。

#### 上位 `note` runのX自動投稿

```bash
python tools/note-sales-team/x_publish_worker.py prepare RUN_ID
# ローカル承認画面で x_publish を別承認後
python tools/note-sales-team/x_publish_worker.py publish RUN_ID
```

`prepare` は認証中のX ID、承認済み告知案、公開済みnote URL、本文と1件目リプをdry-runして事前確認を登録する。`publish` は未使用の `x_publish` claimがなければ外部送信しない。本文の成功を保存してから1件目リプを送信し、両方の公開読み戻しを確認する。

### Step 3: Instagram に投稿

Meta Graph API経由で投稿する。本番投稿はMeta Step6/Step7完了・トークン設定・オーナー承認後のみ実行する。
Instagram本番投稿の画像は、Meta仕様により公開HTTPS画像URLが必要。

dry-run（投稿しない検証）:

```bash
python scripts/post_to_meta.py instagram "キャプション" --image "画像パス" --dry-run
```

本番投稿（直前承認後のみ）:

```bash
python scripts/post_to_meta.py instagram "キャプション" --image-url "https://example.com/image.png" --publish-approved
```

### Step 4: Facebook に投稿

dry-run（投稿しない検証）:

```bash
python scripts/post_to_meta.py facebook "投稿テキスト" [--image "画像パス"] --dry-run
```

本番投稿（直前承認後のみ）:

```bash
python scripts/post_to_meta.py facebook "投稿テキスト" [--image "画像パス"] --publish-approved
```

### Step 5: Threads に投稿（Phase 2で実装予定）

dry-run（投稿しない検証）:

```bash
python scripts/post_to_meta.py threads "投稿テキスト" [--image "画像パス"] --dry-run
```

### Step 5.5: 共通投稿キューのdry-run

1企画から X / Threads / Instagram をまとめて確認する場合:

```bash
python scripts/social_auto_ops.py dry-run ".company/marketing/social-auto-ops/queue/YYYY-MM-DD_slug.json"
```

### Step 6: 結果報告

全投稿の結果を一覧で報告する：

```
投稿結果:
- X: https://x.com/i/status/xxxxx
- Instagram: （投稿URLまたは未実行理由）
- Facebook: （投稿URLまたは未実行理由）
- Threads: （Phase 2で対応）
```

## 対応状況

- [x] X（dry-run / 本番投稿対応済み）
- [x] Instagram（dry-run / 本番投稿対応済み。画像は公開HTTPS URL必須）
- [x] Facebook（dry-run / 本番投稿対応済み）
- [x] Threads（dry-run対応済み / 本番投稿はPhase 2）
- [x] 共通投稿キューdry-run（X / Threads / Instagram）

## ファイル構成

- 認証情報: `~/.ynfactory/credentials/sns-x.env`（ローカル管理、mode 600）。別パスは `YNFACTORY_SNS_CREDENTIALS_FILE` で指定する。Driveやリポジトリ配下に秘密値を保存しない
- X投稿スクリプト: `scripts/post_to_x.py`
- Meta投稿スクリプト: `scripts/post_to_meta.py`
- 共通投稿キューdry-run: `scripts/social_auto_ops.py`
