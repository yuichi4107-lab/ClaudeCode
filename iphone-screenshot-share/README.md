# iPhoneスクショ共有ツール

iPhoneで撮ったスクリーンショットを、Telegram経由でこのPCの
`ピクチャ\iPhoneScreenshots\` フォルダに自動保存します。
家でも外でも（iPhoneがネットに繋がっていれば）使えます。

## 仕組み

```
iPhone: スクショ → 共有シート → Telegram → 専用ボットに送信
PC: receiver.py が受信して画像をフォルダに自動保存
```

## 初回セットアップ（10分）

### 1. 専用ボットを作る（Claude用ボットとは別に必ず新規で）

1. iPhone/PCのTelegramで **@BotFather** を開く
2. `/newbot` を送る → ボット名とユーザー名を決める
3. 表示された **トークン**（`123456:ABC-...` の形）をコピー

> 既存のClaude用ボットのトークンは使わないこと。同じトークンを2つのプログラムで
> 受信すると 409 Conflict エラーになります。

### 2. 設定ファイルを作る

1. `config.example.json` をコピーして `config.json` を作る
2. `config.json` を開き、`bot_token` にコピーしたトークンを貼る
3. 保存する（`allowed_chat_ids` は空のままでOK。次の手順で自動取得）

> `config.json` は `.gitignore` 済みです。Gitで追跡されることはありません。

### 3. 起動して自分のchat_idを登録する

1. `start.bat` をダブルクリックで起動
2. iPhoneのTelegramで、作ったボットを開き **何かメッセージを送る**
3. PCの黒い画面に `SETUP MODE: received from chat_id=XXXXXXXX` と出る
4. その数字（chat_id）を `config.json` の `allowed_chat_ids` に入れる
   例: `"allowed_chat_ids": [12345678]`
5. 黒い画面を閉じ、`start.bat` を再起動

### 4. 使う

1. iPhoneでスクショを撮る
2. 共有シート → Telegram → 作ったボットを選んで送信
3. PCの `ピクチャ\iPhoneScreenshots\` に `YYYYMMDD_HHMMSS.jpg` で保存される
4. Telegramに `OK saved: ...` と返信が来れば成功

## 設定項目（config.json）

| 項目 | 説明 |
|---|---|
| `bot_token` | BotFatherで取得したトークン |
| `allowed_chat_ids` | 受信を許可するchat_idの配列（自分のidのみ推奨） |
| `save_dir` | 保存先。`%USERPROFILE%` 等の環境変数が使える |
| `send_confirmation` | `true`でTelegramに保存完了を返信。不要なら`false` |
| `poll_timeout` | 受信待ちの秒数（既定30） |

## 常駐させたい場合（任意）

- `start.bat` のショートカットを作り、`Win+R` → `shell:startup` で開いた
  スタートアップフォルダに置くと、ログイン時に自動起動します。
- 黒い画面を出したくない場合は、`start.bat` 内の `python` を `pythonw` に
  変えるとウィンドウ無しで常駐します（ログは見えなくなります）。

## 画質について（圧縮されるのが気になる人向け）

- Telegramの共有送信は画像を軽く圧縮（JPEG化）します。通常の閲覧用途では十分です。
- 元のPNGを無劣化で送りたい場合は、iOSショートカットから Bot API の
  `sendDocument` に直接送る「方式B」に拡張できます（受信側 receiver.py は
  document 受信に既に対応済みなので、改修不要）。必要になったら追記します。
- 保存ファイル名は共有送信（方式A）では `.jpg` ですが、方式Bで document として
  送った場合は元の拡張子（`.png` など）で保存されます。

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `409 Conflict ... Exiting` | トークンが他プログラムと重複。**専用ボット**を新規作成して使う |
| 保存されない | `config.json` の `allowed_chat_ids` に自分のchat_idが入っているか確認 |
| `config.json not found` | `config.example.json` をコピーして `config.json` を作る |
| `python` が見つからない | Python 3.8+ をインストールし「Add to PATH」を有効にする |
