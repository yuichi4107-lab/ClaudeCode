# TopView API クライアント

TopView（topview.ai）の残クレジット照会とテキスト→動画生成を CLI から実行する。
標準ライブラリのみで動作する。

## 重要な課金制約

TopView の公式ドキュメントに次の記載がある。

> Ultra credits cannot be used for API requests. API usage is billed only from your
> standard subscription credits, purchased credit packs, and other eligible
> balances—not from Ultra monthly credits.
>
> — <https://docs.topview.ai/docs/billing-rules>

**Ultra プランの月次クレジットは API では消費できない。** API で生成するには
standard subscription（Pro / Business）のクレジットか、別途購入した credit pack が
必要になる。Ultra 契約中でも API 呼び出しは `4100 Credit not enough` で失敗しうる。

`credit` サブコマンドは残高の内訳を返すので、API で使える残高があるかを
実際に叩いて確認するのが確実。

## セットアップ

1. <https://www.topview.ai/api-settings> で API キーと UID を取得する
2. 認証情報を設定する（どちらか）

   環境変数:

   ```bash
   export TOPVIEW_API_KEY="tv_..."
   export TOPVIEW_UID="..."
   ```

   または `.env`（このディレクトリ直下・git 管理外）:

   ```bash
   cp .env.example .env
   # .env を開いて2つの値を記入
   ```

## 使い方

残クレジットの照会:

```bash
python3 tools/topview-api/topview_client.py credit
```

動画生成（9:16・720p・5秒・音声あり）:

```bash
python3 tools/topview-api/topview_client.py generate \
  --prompt "Vertical short video: a calm sunrise over a Japanese horse racing track" \
  --duration 5 --resolution 720 --aspect-ratio 9:16
```

送信せずリクエスト内容だけ確認する:

```bash
python3 tools/topview-api/topview_client.py generate --prompt "test" --dry-run
```

主なオプション:

| オプション | 既定値 | 説明 |
|---|---|---|
| `--model` | `Seedance 1.5 pro` | `Kling V3` / `Sora 2` / `Topview Pro` なども指定可 |
| `--duration` | 5 | 秒数 |
| `--resolution` | 720 | 480 / 720 / 1080 |
| `--aspect-ratio` | 9:16 | ショート動画は 9:16 |
| `--sound` | on | 音声生成の有無 |
| `--poll-interval` | 10 | 完了待ちのポーリング間隔（秒） |
| `--timeout` | 900 | 待機上限（秒） |

生成した動画は `tools/topview-api/output/` に `<taskId>_<n>.mp4` で保存される。
TopView が返す動画 URL には有効期限があるため、スクリプトが即ダウンロードする。

## API 仕様

| 用途 | メソッド | パス |
|---|---|---|
| 残クレジット照会 | GET | `/user/credit/detail` |
| 生成タスク投入 | POST | `/v1/common_task/text2video/task/submit` |
| タスク状態照会 | GET | `/v1/common_task/text2video/task/query` |

ベース URL は `https://api.topview.ai`。認証ヘッダは 2 つとも必須。

```
Authorization: Bearer <your-api-key>
Topview-Uid: <your-topview-uid>
```

エラーコードは `docs.topview.ai/reference/error-response` に準拠し、
スクリプト側で日本語メッセージに変換している。`4100` はクレジット不足、
`4007` は未完了タスクあり。

ドキュメント索引: <https://docs.topview.ai/llms.txt>

## コスト実測値

2026-07-31 に実測した結果（`taskId=fa68a5df69d44b8fabdb81a7926cc001`）。

| 項目 | 値 |
|---|---|
| モデル | Seedance 2.0 |
| 条件 | 5秒 / 9:16 / 720p / 音声あり |
| 消費クレジット | **5.00**（5.52 → 0.52） |
| 単価 | **1.0 クレジット/秒 = $0.10/秒** |
| 1本あたり | **$0.50** |
| 生成時間 | 約 4.5 分 |
| 出力 | H.264 / 5.06秒 / 音声トラックあり / 2.5MB |

音声を on にしても追加消費はなかった。API のモデル名は `Seedance 2.0` を
そのまま指定できる（ドキュメントの例は `Seedance 1.5 pro`）。

Ultra プラン（$600/年 = 500 クレジット/月、1 クレジット = $0.10）の
クレジットは前述のとおり Web UI 専用で、API 残高とは別枠で管理される。
api-settings 画面でも「APIで利用可能」「APIでは利用不可」として区別表示される。
