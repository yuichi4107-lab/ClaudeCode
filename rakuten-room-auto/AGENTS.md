# 楽天ROOM自動投稿システム — エージェント向け引き継ぎ

最終更新: 2026-07-07（Claude Codeセッションで全面改修・稼働確認済み）

## システム概要

Googleスプレッドシートを台帳として、楽天ROOMへ商品を完全自動で投稿するシステム。
launchdが毎日 **12:00 / 20:00 / 22:00** に以下のパイプラインを実行する（各回1件投稿）。

```
replenish → prepare → approve → run
  ①補充      ②準備     ③自動承認   ④投稿
```

1. **replenish**: 残りネタ（未投稿+承認待ち+承認済）が閾値5件以下なら、楽天デイリーランキング3ジャンルから実在商品を5件、テンプレート紹介文付きで「未投稿」追加
2. **prepare**: 未投稿/空ステータス行を「承認待ち」へ（紹介文が空ならLLM生成を試み、無効時は「要確認」）
3. **approve**: 事前チェック（紹介文あり・URL実在HTTP<400・重複なし・同一商品なし）を通った行を「承認済」へ
4. **run**: 承認済の1件を専用Chrome経由で投稿し「完了」へ。投稿後にmy ROOMの商品数増加で成否検証

ステータスフロー: `未投稿 → 承認待ち → 承認済 → 処理中 → 完了`（問題行は `要確認` / `エラー` に退避）

## 環境

| 項目 | 値 |
|---|---|
| コード（正） | リポジトリの `rakuten-room-auto/`（このディレクトリ） |
| 実行環境 | `~/rakuten-room-auto/`（venv・config.yaml・.env・secrets・logs・data） |
| launchd実行用コピー | `~/rakuten-room-auto/app/rakuten-room-auto/`（**コード変更後は必ずrsyncで同期**。install_launchd.sh実行でも同期される） |
| launchdジョブ | `com.ynfactory.rakuten-room-post`（12:00/20:00/22:00） |
| 専用Chrome | プロファイル `~/rakuten-room-auto/.auth/chrome`、CDPポート**9225**、起動は `scripts/start_chrome_room.sh`（run_once.shが未起動なら自動起動） |
| シート | ID `1zh_ojJ7N_LJ6Pqge_CT1aYm2d3STIFBfUQZU92WdLIE` / ワークシート「シート1」 |
| 列名 | 商品URL / 紹介文 / ステータス / 投稿日時 / エラー / 試行回数 |
| ROOMアカウント | プロフィール名「Yuichi」、my ROOM: `room.rakuten.co.jp/room_d0463f2d6c/items` |
| 台帳・ログ | `~/rakuten-room-auto/data/post-ledger.jsonl`、`~/rakuten-room-auto/logs/post.log` |

## コード構成（src/rakuten_room_auto/）

- `runner.py` — パイプライン本体（replenish/prepare/approve/run）。純関数ヘルパー: `check_product_url`（URL実在チェック）、`collect_items`、`count_pipeline_rows` など
- `browser.py` — Playwright+CDPでの投稿処理・ランキング取得（`fetch_ranking_items`）。**エラーメッセージは全て日本語**（シートのエラー列に出るため）。`SUBMIT_NOT_REFLECTED_PREFIX` はrunner側の中断判定と共有される定数
- `replenish.py` — 紹介文生成と同一商品判定の純関数群（下記参照）
- `sheets.py` — Google Sheets読み書き（`append_row_fields` で行追加）
- `config.py` — 設定（`replenish` セクション: enabled/threshold/batch/ranking_urls）
- `statuses.py` — ステータス定義（`pipeline` = 残りネタとして数える集合）

## 同一商品スキップ（重要仕様）

URLが違っても実質同じ商品（例: `tenkapas/glove001` と `glove002`。実際にROOMで重複投稿された事故が発端）を、**補充時・承認時・投稿直前の3段階**で検出し「要確認」に退避する。

- ルール1 `is_same_shop_variant`: 同ショップ＋商品コードの末尾数字違い
- ルール2 `product_similarity` ≥ **0.28**: 紹介文の文字バイグラム・オーバーラップ係数。実データ校正済み（同一商品0.31〜0.82、別商品≤0.26）
- **類似度計算前に必ずテンプレート定型文と `FALLBACK_NAME` を除去する**（`strip_template_boilerplate`）。除去しないと、定型文の共有やフォールバック文言同士の完全一致で別商品が誤検知される（品質チェックで実際に発見された統合バグ。回帰テストあり）
- runの照合対象は完了行のみ。承認済同士の重複はapprove段階で防ぐ設計

## 紹介文の自動生成（景表法対策込み）

- `build_description`: 3テンプレートをローテーション。`clean_item_title` がクーポン等の販促ノイズ（`NOISE_TOKEN_PATTERN`）と誇大表現（`EXAGGERATED_TOKEN_PATTERN`: No.1/最強/圧倒的/\d+位 等）を除去。全滅時は `FALLBACK_NAME`
- 手書き紹介文（シート直接入力）にはフィルタがかからない点に注意

## 運用コマンド（リポジトリルートから実行）

```bash
source ~/rakuten-room-auto/.env
PY="~/rakuten-room-auto/.venv/bin/python"
export PYTHONPATH=rakuten-room-auto/src

$PY -m rakuten_room_auto preview --limit 5     # 候補確認（読み取りのみ）
$PY -m rakuten_room_auto check-session         # ROOMログイン確認（読み取りのみ）
$PY -m rakuten_room_auto replenish [--dry-run] # ネタ補充
$PY -m rakuten_room_auto prepare --limit 10    # 未投稿→承認待ち
$PY -m rakuten_room_auto approve --limit 10    # 承認待ち→承認済（事前チェック付き）
$PY -m rakuten_room_auto run --limit 1 [--dry-run]  # 投稿（dry-runは送信ボタンを押さない）
```

テスト: `PYTHONPATH=src ~/rakuten-room-auto/.venv/bin/python -m pytest tests/`（25件、全合格の状態を維持すること）

## 過去の障害と教訓（再発防止）

1. **でっち上げ404 URL**: シートに実在しない商品URL（連番類推）が8行混入し「投稿ボタンが見つからない」エラーを量産した。→ URLは楽天ランキング由来の実在URLのみ使う。approveにHTTP事前チェックあり
2. **launchd が disabled**: `launchctl print-disabled gui/501` に disabled 登録されていると bootstrap が「Input/output error」で失敗する。→ `launchctl enable gui/501/com.ynfactory.rakuten-room-post` してから bootstrap
3. **「送信したが商品数が増えない」**: 投稿が実際には反映されていないサイン。ledgerの `posted` は商品数増加を検証済みの記録
4. **ランキングページは直接curl不可（403）**: 必ず専用Chrome（CDP 9225）経由で取得する
5. **類似度判定の定型文除去漏れ**: テンプレート文・FALLBACK_NAMEを除去せず比較すると別商品が誤検知される

## 現在の状態（2026-07-07時点）

- ROOMには4商品投稿済み（シート行2,3,4,11が「完了」）
- 承認済（投稿待ち）5件: 行5,6,15,16,19（全て別商品であることを153ペア監査で確認済み）
- 要確認9件: 404 URL×7行（行7-10,12-14。URL差し替えが必要）＋同一商品スキップ×2行（行17,18。とろとろケット重複）
- launchd有効。次回実行時に残りネタ5件=閾値のため自動補充が発動する見込み

## Codexオートメーションとの排他（重要）

Codex側に同じシステムを操作するオートメーションが2つ存在する（`~/.codex/automations/`）。

- `rakuten-room-post` — 毎日12:00/20:00/22:00に1件投稿（**launchdと完全に同一スケジュール**）
- `room-20` — 水・土15:00に候補20件補充

**2026-07-07 21:01に両方PAUSEDへ変更済み。launchdジョブが有効な間は絶対に再開しないこと**（2026-07-07に両方が稼働して1日5件の二重投稿が発生した実績あり）。投稿・補充はlaunchd側のパイプラインに一本化されている。Codexで作業する際、投稿の確認は `--dry-run` / `preview` を使い、`run` の本番実行はオーナーの明示指示があるときだけにする。

## 作業ルール

- **投稿（ROOMへの送信）と定期実行の有効化は、必ず直前にオーナーの明示承認を取る**。シートの書き換え（補充・承認）はオーナー承認済みの自動化の範囲内
- 変更後は: pytest全合格 → `~/rakuten-room-auto/app/rakuten-room-auto/` へrsync同期 → 必要ならdry-runで検証
- git commit/pushは**Windows側でのみ**行う（Drive側では git 操作をしない。Macは.gitがWindowsパス固定のためcommit不可）
- シートのエラー列に出るメッセージは非エンジニアが読むため**日本語で書く**（回帰テスト `test_browser_error_messages_are_japanese` あり）

## 未対応・改善候補

- 紹介文のAI生成（OpenAIキー設定で `llm.enabled: true` にすれば prepare 時に生成。現在はテンプレート方式）
- `\d+位` パターンが「3位置調整」等の通常表現も保守的に除去する（実害小、`\d+位(?!置)` で精度向上可）
- `check_product_url` のUser-Agent固定（Chrome/126）はいずれ古くなる
- README「同一商品スキップ」節にFALLBACK_NAME時はURL判定のみになる旨の追記
- 行5・6の手書き紹介文に「履くだけで美脚」等の効果標榜表現が残っている（オーナー確認待ち）
