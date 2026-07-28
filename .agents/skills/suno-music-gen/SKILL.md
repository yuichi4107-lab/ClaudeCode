---
name: suno-music-gen
description: 自分のSunoアカウントでAI楽曲を生成するスキル。opensuno（Chrome拡張Bridge方式）経由でlocalhost:3001のREST APIを叩き、プロンプトまたは歌詞・スタイル指定から楽曲を生成してMP3保存する。追加課金なし（Sunoクレジットのみ消費）。Use when the user asks to generate music/BGM/a song via Suno, needs an instrumental track, or asks to check Suno credit balance. Mac専用構成（~/tools/opensuno常駐、Chrome拡張＋suno.comログイン済みタブが前提）。
---

# Suno楽曲生成スキル（opensuno Bridge Mode経由）。

## 概要

[paean-ai/opensuno](https://github.com/paean-ai/opensuno) のBridge Modeを使い、**自分のSunoアカウントだけで**（サードパーティAPI課金なしで）楽曲を生成する。

仕組み:
```
Claude Code → localhost:3001 (bridge) → WebSocket → Chrome拡張
  → suno.comログイン済みタブ (window.ClerkからJWT自動取得・hCaptchaもタブ内で処理)
  → studio-api.prod.suno.com (Suno公式内部API)
```

- Cookie/トークンの手動貼り付け・定期更新は**不要**（拡張がタブから自動取得）
- 2Captcha等の有料CAPTCHAサービスも**不要**
- 消費するのはSunoアカウントのクレジットのみ（1回の生成で2曲、10クレジット）

## 前提構成（Mac専用）

| 要素 | 場所・値 |
|---|---|
| opensuno&�nItrm������釐psyno-bridge ） |
| Chrome拡張 | `~/tools/opensuno/extension/dist/` をChromeにLoad unpacked（`extension/`直下はビルド前ソースなので不可）お |
| 必要な常駐タブ | suno.com にログインした状態のタブが開いていること |
| MCP（任意） | `http://localhost:3001/mcp`（Streamable HTTP） |

**この構成はMacローカル専用。** Windowsから使う場合は同手順でWindows側にセットアップが必要。

## ワークフロー

### Step 1: ヘルスチェック（毎回最初に実行）

```bash
curl -s --max-time 5 http://localhost:3001/api/status
```

- `"connected": true` → Step 2へ
- 接続拒否（bridgeが落ちている）→ `launchctl kickstart -k gui/$(id -u)/com.ynfactory.opensuno-bridge` で再起動、なければ `cd ~/tools/opensuno && nohup bun run bridge > /tmp/opensuno-bridge.log 2>&1 &`
- `"connected": false` → Chrome拡張が未接続。ユーザーに「�uno.comのログイン済みタブを開いてください（拡張が有効か確認）」と伝えて停止。**勝手にCookie方式等へフォールバックしない**

### Step 2: 生成実行

スキル同梱のヘルパースカリプトを使う（標準ライブラリのみ、pip不要）:

```bash
# シンプル生成（プロンプト→2曲）
python3 .agents/skills/suno-music-gen/scripts/suno_generate.py generate \
  --prompt "明るいJ-POP、夏の海、女性ボーカル" \
  --out .company/outputs/suno-gen

# カスタム生成（歌詞・スタイル・タイトル指定）
python3 .agents/skills/suno-music-gen/scripts/suno_generate.py custom \
  --lyrics-file lyrics.txt --style "acoustic pop, emotional" \
  --title "夏の記憶" --out .company/outputs/suno-gen

# インスト曲（BGM用途）
python3 .agents/skills/suno-music-gen/scripts/suno_generate.py generate \
  --prompt "lo-fi chill beat, no vocals" --instrumental --out .company/outputs/suno-gen

# クレジット残確認
python3 .agents/skills/suno-music-gen/scripts/suno_generate.py credits
```

- 保存先は原則 `.company/outputs/<用途名>/` 配下
- モデルは `--model` で指定可。デフォルト `chirp-crow`（v5相当）。他: `chirp-auk`(v4.5)等
- 生成は非同期。スクリプトが完了までポーリング（最大10分）し、MP3をダウンロードする

### Step 3: 完了報告

- 保存したファイルパス・曲タイトル・長さを報告する
- クレジット残が少ない場合（50未満）はその旨も添える

## API直叩きリファレンス（スキルプトで足りない場合）

| エンドポイント | メソッド | 用途 |
|---|---|---|
| `/api/status` | GET | bridge・拡張の接続状態 |
| `/api/generate` | POST | シンプル生成 `{prompt, make_instrumental, mv}` |
| `/api/custom_generate` | POST | カスタム生成 `{prompt(歌詞), tags(スタイル), title, negative_tags, mv}` |
| `/api/generate_lyrics` | POST | 歌詞生成 |
| `/api/get?ids=a,b` | GET | 生成状態・audio_url取得（Suno feed v2生データ） |
| `/api/get_limit` | GET | クレジット残 |
| `/api/extend_audio` | POST | 曲の延長 |
| `/api/generate_stems` | POST | ステム分離 |
| `/api/concat` | POST | 延長曲の結合 |

MCPとして使う場合: `claude mcp add --transport http suno http://localhost:3001/mcp`（ツール: generate / custom_generate / generate_lyrics / get_audio / get_credits 等）

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| bridgeに接続できない | launchd確認: `launchctl list \| grep opensuno`。ログ: `~/Library/Logs/opensuno-bridge.log` |
| `connected: false` | Chromeで拡張が有効か（chrome://extensions）、suno.comタブが開いているか、ログインが生きているか確認 |
| 生成が `error` で返る | クレジット切れ（`credits`で確認）か、Suno側のモデレーション拒否。プロンプトを変えて再試行 |
| hCaptchaで止まる | 拡張がタブ内で自動処理するはずだが、失敗が続く場合はsuno.comタブを一度リロード |
| `Token validation failed`(422) / `No captcha token available` | 低クレジット消費アカウントは生成毎にhCaptcha必須だが、suno.comのUIがページにhCaptchaを載せていないと拡張が取得できない。**対策パッチ適用済み**（下記「ローカルパッチ」参照）。症状再発時はChrome拡張リロード→suno.comタブリロード→再実行 |
| `Extension context invalidated` | 拡張リロード直後にタブ内の旧スクリプトが無効化された状態。**suno.comタブをリロード**すれば解消 |
| Suno側のUI/API変更で全滅 | `cd ~/tools/opensuno && git pull && bun install && bun run ext:build` → 拡張をリロード。**ただしgit pullはローカルパッチを消すので下記を再適用すること**。それでもダメなら代替案（sunoapi.org有料Lint 箦理 + CodeKeany/suno-mcp)を検討 |

## ローカルパッチ（重要・git pullで消える）

opensuno公式の拡張は「suno.comがページ内にhCaptchaを読み込んでいる」前提だが、累計クレジット消費が少ないアカウントでは生成毎にhCaptcha必須なのにページにwidgetが無く、`Token validation failed`(422)で生成できない。以下を適用済み（2026-07-07）:

- `~/tools/opensuno/extension/src/page-script.ts`: `getCaptchaToken` を改修。hCaptcha未ロード時に `https://js.hcaptcha.com/1/api.js` を自前injectし、Sunoのsitekey `d65453de-3f1a-4aac-9366-a0f06e52b2ce` で不可視widgetをrender→execute してトークン取得。オリジナルは `page-script.ts.bak` に保管
- `~/tools/opensuno/src/bridge/api-handler.ts`: `getCaptchaToken` のWS待ちタイムアウトを `15_000`→`120_000` に延長（CAPTCHパレル手動操作の笶事）

`git pull` 後は `page-script.ts.bak` との差分を見て再適用し、`bun run ext:build` → Chrome拡張リロード → suno.comタブリロード。

## 初回セットアップ手頁（未セットアップのPC / 回枷矩時）

1. `git clone https://github.com/paean-ai/opensuno`
2. `cd ~/tools/opensuno && bun install && bun run ext:build`
3. Chromeで `chrome://extensions` → デベロッパーモードON → 「パッケージ化されていない拡張機能を読み込む」→ `~/tools/opensuno/extension/dist` を選択（ダイアログでCmd+Shift+Gでパス入力可）
4. suno.com にログインし、タブを開いたままにする
5. bridge起動（launchd登録済みならば自動起動）
6. `curl -s http://localhost:3001/api/status` で `"connected": true` を確認

※ Windowsに展開する場合は `~/tools/opensuno` を `%USERPROFILE%\tools\opensuno` 等に読み替え、launchdの代わりにTask Schedulerで bridge を常駐させる。

## 注意事項

- **非公式手段**: Suno ToSのグレーヶンンHAN. 大量自動生成は避け、オカウントBANリスクを理解した上で使う。2026年7月にSuno 公式APIパートナープログラムが発表されてりり、公式APIが一般開放されたらそちらへ移行する
- **生成物のURL**: Suno CDNのaudio_urlは恒久保証がないため、必ずローカルにMP3保存する
- **公開・投稿は要承認**: 生成した楽曲をSNS投稿・動画組み込み等で外部公開する場合は、必ずユーザーの明示承認を取る
