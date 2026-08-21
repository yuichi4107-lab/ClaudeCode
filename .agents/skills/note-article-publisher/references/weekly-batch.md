# 週次バッチモード（5アカウント × 7日 = 35記事）

毎日の制作作業を減らすため、週に1回まとめて7日分を下書きまで作る。上位 `note` runと組み合わせる場合は、各記事の確認後に `note_publish` を別承認し、対象の下書きだけを自動公開する。

## 前提

- 5アカウントすべてに、対応する `browser_profile` でログイン済み
- `accounts.json` に5アカウント分のエントリが入っている
- `topics/<account_id>.md` にトピックキューがある（空ならClaudeが補充する）
- `history.json` が初期化されている

## ディレクトリ規約

週次バッチの出力は週単位フォルダにまとめる。

```
.company/outputs/note-articles/
├── accounts.json
├── history.json
├── topics/
│   ├── ai.md
│   ├── money.md
│   ├── career.md
│   ├── spiritual.md
│   └── love.md
└── weekly/
    └── 2026-W20/                  # ISO週番号
        ├── plan.md                # 7日×5アカウントの一覧表
        ├── 2026-05-18-ai-xxx/     # 月曜分
        ├── 2026-05-18-money-xxx/
        ├── 2026-05-18-career-xxx/
        ├── 2026-05-18-spiritual-xxx/
        ├── 2026-05-18-love-xxx/
        ├── 2026-05-19-ai-xxx/     # 火曜分
        ...
        └── 2026-05-24-love-xxx/
```

## 実行フロー（週次バッチ）

### Step W1: 週の計画を立てる

1. 今日の日付と次週の月曜〜日曜の7日分の日付をツールで確認する。
2. `accounts.json`、`history.json`、各 `topics/<account>.md` を読む。
3. 5アカウント × 7日 = 35テーマを決める。
   - 各アカウントの `topics/<account>.md` から上から順に消化
   - キューが7件に満たないアカウントは、`history.json` の直近30日と被らない切り口でClaudeが補充
4. `plan.md` に以下の表で書き出す。

```markdown
# 週次計画 2026-W20 (2026-05-18 月 〜 2026-05-24 日)

| 日付 | 曜日 | account_id | theme_id | テーマ | 切り口 | 出典 |
|------|------|------------|----------|--------|--------|------|
| 2026-05-18 | 月 | ai | ai-workplace | ChatGPT議事録短縮 | 自分の実例3つ | topics/ai.md |
| 2026-05-18 | 月 | money | money-everyday | 新NISA15年シミュ | 月3万円ケース | topics/money.md |
...
```

5. オーナーに `plan.md` を見せて承認を得る。

### Step W2: 35記事をループで生成

承認後、`plan.md` を上から順に処理する。1記事あたりの処理は既存ワークフロー（Step 1〜Step 7）に準拠する。

1. アカウントの `persona_file` を読み込み、トーン・文字数・NG・構成を取得する。
2. `history.json` で直近30日同アカウント記事との重複を確認する。
3. リサーチ（必要に応じてWebSearch・context7）→ 構成 → 本文 → カバー1枚 + 挿絵2-3枚 を生成。
4. `note-post-ready.md` / `article.md` / `image-placement.md` / `quality-check.md` を出力。
5. 85点未満なら同記事内で修正してから次の記事に進む。
6. `history.json` に `status: "queued"` で追記（まだ下書き未投入）。

### Step W3: noteへ下書き投入

35記事が出来上がったら、アカウントごとにまとめてブラウザ操作する。

1. アカウント `ai` の `browser_profile` で note を開く。
2. ログイン中アカウントが `display_name` と一致するか確認する。
3. その週の `ai` 分7記事を1記事ずつ:
   - 新規記事画面 → タイトル貼付 → 本文貼付
   - 見出し画像アップロード（縦長表示にトリミング）
   - 本文中画像を指定位置に挿入
   - `下書き保存` を押し、保存済み表示を確認
   - 下書きURLを `history.json` の `draft_url` に書き戻す
   - `status: "draft"` に更新
4. 同様に money → career → spiritual → love の順で進める。

### Step W4: オーナーへ確認依頼

1. 週次バッチ完了サマリを `weekly/2026-W20/summary.md` に出力。
   - 35記事のうち何件が draft、何件が PARTIAL（画像未反映など）か
   - 各記事の `draft_url` 一覧
2. `quality-check.md` で問題が出た記事をリストアップ。
3. オーナーは対象記事の `draft_url` と公開設定を確認する。上位 `note` runで運用する場合は、ローカル画面で `note_publish` を承認し、公開ボタンの操作と公開URLの読み戻しはAIに任せる。

## 生成バッチと公開工程を分離する

週次の35記事生成バッチ本体は下書きまでで終了し、公開は記事ごとの `note_publish` 工程として分離する。理由:

- 35記事を一気に公開するとnote側のスパム検知に引っかかる可能性がある
- 公開後に修正したい誤字脱字や事実誤認が見つかったときに取り消せない
- 投稿時間を分散させた方が露出も伸びる

単体でこのバッチだけを使う場合は、公開は引き継ぎ後の別作業とする。上位 `note` runから使う場合は、記事単位の事前確認・明示承認・1回限りのclaim後に自動公開し、結果不明時は再操作せず照合する。

## キューが空のときの自動補充

ある `topics/<account>.md` が7件未満だった場合:

1. その `account_id` の `theme_id` の `preferred_angles` を見る
2. `history.json` の直近30日エントリから、その account_id で出てない切り口を探す
3. WebSearch で最近のトレンド（1ヶ月以内）を1-2件参考にする
4. Claudeが不足分を補い、補ったテーマを `topics/<account>.md` の末尾にコメント付きで追記する（次週以降の透明性のため）

## 失敗時のリカバリ

- ある記事の生成で詰まったら、その1記事だけ `plan.md` で `status: failed` にマークし、次の記事に進む
- 35記事すべての処理後、failed のものをオーナーに報告する
- ブラウザ投入で詰まったアカウントは、その週はそのアカウントだけ翌日に再試行
