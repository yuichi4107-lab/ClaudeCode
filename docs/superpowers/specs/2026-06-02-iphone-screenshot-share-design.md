# iPhoneスクショ共有ツール 設計書

- 日付: 2026-06-02
- 種別: 新規ツール（Windows常駐 + Telegram橋渡し）
- 方式: 案1（専用Telegramボット橋渡し）／iPhone送信方式A（Telegramアプリから送信）を初期、Bは将来拡張

## 1. 目的・背景

iPhoneで撮ったスクリーンショットを、Windows PCへ**簡単に・家でも外でも**共有したい。
AirDropはWindows非対応、iCloud写真は重い、ケーブルは面倒。既に環境にTelegramが設定済みのため、Telegramを「橋渡し」に使うことで、同一Wi-Fiに依存せずどこからでも送れる仕組みを最小コストで実現する。

## 2. 要件（確定事項）

確定済み（ユーザー承認）:

- ネットワーク: 家でも外でも使う → 同一LAN非依存（クラウド経由）が必須
- PC側の挙動: **フォルダに自動保存のみ**（クリップボード/通知/自動表示は今回スコープ外）
- iPhone側: まず方式A（Telegramアプリから送信）。気に入ったら方式B（iOSショートカットでワンタップ無劣化送信）を追加
- 既存資産: Telegramを活用
- 保存先: `%USERPROFILE%\Pictures\iPhoneScreenshots\`
- Telegramへの「✅保存しました」返信: 有り（設定でOFF可能）
- フォルダ名: `iphone-screenshot-share/`（リポジトリ直下）

### スコープ外（YAGNI）

- クリップボード自動コピー / Windowsトースト通知 / ビューアー自動表示
- 自前VPSアップロード口（案2）
- 同一LAN内Webアップロード（案3）
- 双方向同期・既存写真の一括取り込み・動画対応（画像のみ）

## 3. アーキテクチャ（データフロー）

```
iPhone: スクショ → 共有シート → Telegram → 専用ボット に送信
                                              │  (Telegramサーバー経由・どこからでも)
PC(Windows): receiver.py が long-poll(getUpdates) で受信
            → getFile → 画像ダウンロード
            → %USERPROFILE%\Pictures\iPhoneScreenshots\ に保存
            → （任意）Telegramに「✅ 保存しました: <filename>」と返信
```

- 即時性: long-poll（timeout=30秒）でほぼ即時・低CPU
- 依存: **専用ボット**（Claude用ボットとは別トークン。同一トークンの二重受信は409衝突するため必須）

## 4. 構成ファイル（`iphone-screenshot-share/`）

| ファイル | 役割 | git追跡 |
|---|---|---|
| `receiver.py` | 本体。Telegram長ポーリング→画像保存。**Python標準ライブラリのみ**（`urllib`+`json`、pip不要） | する |
| `config.example.json` | 設定雛形（token / save_dir / allowed_chat_ids / send_confirmation） | する |
| `config.json` | 実設定（トークン含む） | **しない（.gitignore）** |
| `state.json` | 受信位置(update offset)の永続化。再起動時の重複/取りこぼし防止 | **しない（.gitignore）** |
| `start.bat` | 起動ランチャー。**ASCII文字のみ**（CP932誤読対策。日本語案内はREADMEへ） | する |
| `README.md` | セットアップ手順（日本語） | する |
| `tests/` | 純ロジックのユニットテスト | する |
| `.gitignore` | `config.json` / `state.json` を除外 | する |

> Python標準ライブラリのみとし、`pip install`不要で起動可能にする（ユーザー導入の摩擦を最小化）。

### config.json スキーマ

```json
{
  "bot_token": "123456:ABC-...",
  "allowed_chat_ids": [123456789],
  "save_dir": "%USERPROFILE%\\Pictures\\iPhoneScreenshots",
  "send_confirmation": true,
  "poll_timeout": 30
}
```

- `save_dir`: 環境変数（`%USERPROFILE%`等）を展開して使う。未指定なら既定値。
- `allowed_chat_ids`: 空の場合は「未設定モード」として受信せず、受け取ったchat_idをログ表示（初回セットアップ補助）。

## 5. コンポーネント分割（テスト可能な純ロジックとI/Oを分離）

| ユニット | 入力 → 出力 | 依存 |
|---|---|---|
| `extract_image(message)` | Telegram message dict → `(file_id, ext)` or `None`。photoは最大サイズ選択、document(image/*)はそれを採用 | なし（純関数） |
| `build_filename(dt, ext, existing)` | 日時・拡張子・既存ファイル集合 → 衝突回避済みファイル名 `YYYYMMDD_HHMMSS[_NN].ext` | なし（純関数） |
| `is_allowed(chat_id, allowlist)` | chat_id・許可リスト → bool | なし（純関数） |
| `TelegramClient` | getUpdates / getFile / downloadFile / sendMessage | network（urllib）。テストはモック |
| `Receiver`（メインループ） | 上記を束ねる。offset永続化・例外時リトライ | TelegramClient・ファイルIO |

「何をするか／どう使うか／何に依存するか」が各ユニットで明確。純関数群はネットワーク無しで単体テスト可能。

## 6. エラー処理

| 事象 | 挙動 |
|---|---|
| 通信エラー / タイムアウト | ログ出力しリトライ。**プロセスは落とさず回り続ける**（指数バックオフ上限あり） |
| `409 Conflict`（同トークン二重受信） | 数回だけ間隔をあけて再試行 → 解消しなければ「Claude用ボットと別の専用ボットを使ってください」と明示ログを出して終了（非ゼロ終了コード）。設定起因のため自動回復は狙わない |
| 未許可chat_idからの受信 | 無視してログ記録（情報漏えい防止のため返信はしない） |
| 保存先フォルダ不在 | 起動時に自動作成 |
| ファイル名衝突 | `_01`,`_02`... の連番付与で回避 |
| 画像以外（テキスト等）の受信 | 無視（任意で「画像を送ってください」返信は将来検討、初期は無視） |
| ダウンロード失敗 | ログ出力し当該更新はスキップ、offsetは進める（無限ループ防止） |

## 7. セキュリティ（過去に機密誤push事故あり・最優先）

- **chat_id許可リスト必須**: 自分のID以外からの画像は受信しない。ボット名が露見しても他人がPCにファイルを置けない。
- **トークンは`config.json`のみに保持し`.gitignore`で除外**。`config.example.json`にトークンを書かない。リポジトリ直下の`.gitignore`にも二重で登録を検討。
- 初回起動補助: `allowed_chat_ids`未設定時は受信chat_idをログ表示するだけ（保存しない）→ 自分のIDを貼って再起動。
- 保存ファイル名はスクリプト側で生成（タイムスタンプ）するため、送信者由来のパストラバーサルは発生しない。
- ダウンロードサイズはTelegram Bot APIの制約（~20MB）内。画像のみ受理。

## 8. テスト方針（TDD・CLAUDE.md品質ループ準拠）

- 純ロジックの単体テスト（ネットワーク不要）:
  - `extract_image`: photo配列から最大解像度を選ぶ / document(image/png)を拾う / 非画像はNone
  - `build_filename`: 通常生成 / 同名衝突時の連番 / 拡張子保持
  - `is_allowed`: 許可/不許可/空リスト
- `TelegramClient`はモックで`Receiver`の分岐（許可外スキップ・保存・offset更新）を検証
- 手動E2E: 実機iPhoneからスクショを1枚送り、保存とTelegram返信を確認
- フレームワーク: 標準`unittest`（追加依存なし）。`tests/`配下。

## 9. 起動・常駐

- `start.bat`（ASCIIのみ）で `python receiver.py` を起動。
- 常時起動したい場合は `shell:startup` に`start.bat`のショートカットを置く手順をREADMEに記載（任意・コア外）。
- バックグラウンド化（`pythonw`）も任意でREADMEに併記。

## 10. 将来拡張（今回はやらない／設計上の受け皿のみ）

- **方式B（iOSショートカット）**: 共有シート→ワンタップで Bot API `sendDocument` に直接POST → 元PNGを無劣化送信。`receiver.py`は`document`対応済みのため**受信側の改修不要**。READMEに後日手順を追記する想定。
- クリップボード自動コピー / トースト通知 / ビューア表示（configフラグで段階的に追加可能な構造にしておく）。

## 11. 完了条件（チェックリスト）

- [ ] `iphone-screenshot-share/` 一式が作成され、`config.json`/`state.json`が`.gitignore`される
- [ ] `python receiver.py` が起動し、long-pollで待機する
- [ ] 許可chat_idからのphoto/documentを保存先に保存できる
- [ ] 未許可chat_idは無視される
- [ ] 409衝突時に分かりやすいログを出す
- [ ] 純ロジックの単体テストが全て通る
- [ ] READMEの手順だけで第三者がセットアップ→送信→保存まで到達できる
- [ ] 実機E2Eでスクショ1枚の保存を確認
