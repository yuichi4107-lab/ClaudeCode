# GitHub Actions 自動投稿 セットアップ（v1・バックアップ用）

> ⚠️ **このドキュメントはv1（GitHub Actions方式）の手順です。**
> 現在の推奨はv2（GAS方式）です。通常は [`skills/gas-x-post/SETUP.md`](../skills/gas-x-post/SETUP.md) を使用してください。

## 投稿スケジュール（日本時間）

| 時刻 | 理由 |
|------|------|
| 07:00 | 通勤時間帯① |
| 08:30 | 通勤時間帯② |
| 12:00 | 昼休み① |
| 13:00 | 昼休み② |
| 17:30 | 帰宅時間帯 |
| 19:00 | 帰宅〜夜① |
| 20:00 | ゴールデン① |
| 21:00 | ゴールデン②（最高エンゲージ） |
| 22:00 | ゴールデン③ |
| 22:30 | ゴールデン④ |

## GitHub Secrets の設定（初回のみ）

1. `https://github.com/あなたのユーザー名/X-skill/settings/secrets/actions` を開く
2. 「New repository secret」で以下を追加：

| Secret名 | 値の場所 |
|----------|---------|
| `API_KEY` | .env の API_KEY |
| `API_KEY_SECRET` | .env の API_KEY_SECRET |
| `ACCESS_TOKEN` | .env の ACCESS_TOKEN |
| `ACCESS_TOKEN_SECRET` | .env の ACCESS_TOKEN_SECRET |
| `GEMINI_API_KEY` | .env の GEMINI_API_KEY |

## 投稿ストックの追加方法

`queue/queue.json` に追記するだけ：

```json
[
  {
    "id": "post-001",
    "text": "投稿したいテキスト（何文字でも可）",
    "image_prompt": "NanoBanana2に渡すプロンプト（画像不要ならnull）",
    "image_path": null,
    "created_at": "2026-03-19T10:00:00"
  },
  {
    "id": "post-002",
    "text": "2本目の投稿",
    "image_prompt": null,
    "image_path": "queue/images/post-002.png",
    "created_at": "2026-03-19T10:00:00"
  }
]
```

## 動作フロー

```
スケジュール時刻になる
  ↓
GitHub Actions 起動
  ↓
queue.json の先頭1件を取得
  ↓
image_prompt があれば Gemini API で画像生成
  ↓
X に投稿（画像あり or なし）
  ↓
queue.json から削除 → コミット・プッシュ
```

## 手動テスト方法

GitHub の Actions タブ → 「X自動投稿」→「Run workflow」
- `dry-run: true` にすると投稿せず確認のみ

## キューが空のとき

投稿はスキップされます（エラーにはなりません）。
キューが空になる前に Claude Code でストックを補充してください。
