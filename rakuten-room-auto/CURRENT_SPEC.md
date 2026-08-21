# 楽天ROOM自動投稿システム 現状仕様（As-Is）

基準日: **2026-07-27 JST**  
用途: Claude Codeが現行実装を誤解せず、安全にブラッシュアップするための技術・運用基準書  
対象: `rakuten-room-auto/` のソース、Mac上の実行コピーとランタイム、Google Sheets、楽天ROOM、launchd

## 0. この文書の位置づけ

この文書は、READMEや過去の引き継ぎだけでなく、2026-07-27時点のソースコード、テスト、launchd設定、読み取り専用のライブ状態を照合して作成した現状仕様である。

- As-Isを記録する文書であり、ここに書かれた改善案が実装済みという意味ではない。
- 認証情報、OAuthトークン、APIキー、Chromeプロファイルの内容は記載しない。
- この文書作成ではコード、設定、シート、ROOM、launchd、Codex automationを変更していない。
- 本番投稿、外部状態の変更、スケジューラ変更は、実行直前のオーナー明示承認なしに行わない。

## 1. As-Isアーキテクチャ

```text
Google Sheets（商品・紹介文・状態）
       │
       │ Google Sheets API / OAuth
       ▼
run_once.sh
  ├─ preview --limit 1        Sheet/ROOM非変更のOAuth preflight
  ├─ replenish                楽天ランキングから候補補充
  ├─ prepare                  未投稿 → 承認待ち
  ├─ approve                  事前検査 → 承認済 / 要確認
  └─ run --limit 1            承認済 → 処理中 → 完了 / エラー
       │
       │ Playwright CDP
       ▼
専用Chrome（CDP 9225） ── 楽天市場商品ページ / 投稿画面 / 公開my ROOM
       │
       ├─ 公開my ROOMの商品数増加を確認
       └─ ledger / log / Sheetへ結果を記録

launchd（12:00 / 20:00 / 22:00 JST）
       └─ 実行コピー内の run_once.sh を起動
```

主な実装:

- `src/rakuten_room_auto/runner.py`: 4工程とシート状態更新
- `browser.py`: CDP接続、ランキング取得、投稿、公開商品数確認
- `sheets.py`: Google Sheets読み書きとOAuth refresh
- `replenish.py`: タイトル整形、テンプレート紹介文、同一商品推定
- `ledger.py`: JSON Lines形式のイベント追記
- `scripts/run_once.sh`: OAuth preflightと4工程の定期実行
- `launchd/com.ynfactory.rakuten-room-post.plist`: 1日3回の起動定義

## 2. 正本・実行コピー・ランタイム

| 区分 | 場所・役割 | 注意 |
|---|---|---|
| ソース正本 | Drive共有コピーの `rakuten-room-auto/` | コード・文書の編集場所。Drive側でGit操作しない |
| launchd実行コピー | `~/rakuten-room-auto/app/rakuten-room-auto/` | launchdが実際に起動するコード。正本変更だけでは本番に反映されない |
| ランタイム | `~/rakuten-room-auto/` | `.venv`、`config.yaml`、`.env`、`secrets/`、`data/`、`logs/`、専用Chromeプロファイルを保持 |
| 投稿台帳 | `~/rakuten-room-auto/data/post-ledger.jsonl` | append-onlyの監査材料。ただし現行コードは重複判定の入力には使わない |
| 実行ログ | `~/rakuten-room-auto/logs/post.log` | launchd標準出力・標準エラー。単独では投稿成功の証拠にしない |

`scripts/install_launchd.sh` は正本を実行コピーへ `rsync --delete` し、その後LaunchAgentを配置・再読込する。したがって単なる「同期」ではなく、次回以降の本番挙動を変える操作である。実行には直前の明示承認が必要。

2026-07-27 21:55 JSTの確認時点では、CURRENT_SPEC.md作成前の正本と実行コピーに差分はなかった。

## 3. 定期パイプライン

launchdの定刻は毎日 **12:00 / 20:00 / 22:00 JST**。各回の投稿上限は1件。

### 3.1 OAuth preflight

`run_once.sh` は、外部状態を変更する工程より先に次を実行する。

```bash
python -m rakuten_room_auto preview --limit 1
```

目的:

- OAuthトークンを読み込めるか
- 必要ならrefreshできるか
- Sheets APIで対象シートを読めるか
- 必須列があるか

このpreflightはSheetのセルやROOMを変更しない。ただし、既存OAuth認可の通常refreshが成功した場合は、`sheets.py` がローカルのtoken JSONを更新し得る。完全なファイル非変更処理ではない。

OAuth refreshが `invalid_grant` 等で失敗した場合、`sheets.py` は秘密情報を含めない日本語の `SheetError` に変換し、`set -e` により後続の補充・状態変更・投稿へ進まない。この「Sheet・ROOMの変更前に止まる」性質は維持すべき安全要件である。

注意:

- Google OAuth成功だけでなく、対象Google CloudプロジェクトでSheets APIが利用可能である必要がある。
- 既存認可内の自動refreshは通常実行の一部。`scripts/setup_google_oauth.py` による手動再認証、認可範囲の変更、tokenファイルの手動交換・削除は明示承認が必要。
- 現行コードには、一部の一般的なトークン不正メッセージが英語のまま残る。

### 3.2 replenish

条件:

- `replenish.enabled: true`
- ランキングURLが設定済み
- 「空欄・未投稿・承認待ち・承認済」の商品行数が閾値以下。既定は5件以下

動作:

1. 専用Chromeで楽天デイリーランキングを開く。
2. 3ジャンルから商品URLとタイトルを抽出する。
3. シート内の既存URLと同一商品推定に該当する候補を除外する。
4. 最大5件をテンプレート紹介文付きの `未投稿` として追記する。
5. 本番実行時は `replenish` または `replenish_error` をledgerに追記する。dry-runでは候補追加のledgerを書かない。

ランキングページは直接HTTP取得が403になることがあるため、現行実装はCDP接続した専用Chromeを使用する。

### 3.3 prepare

対象: ステータスが空欄または `未投稿` の行。

- 紹介文あり: `承認待ち`
- 紹介文なし、LLM有効かつ生成成功: 生成文を書いて `承認待ち`
- 紹介文なし、LLM無効または生成失敗: `要確認`

既定ではLLM紹介文生成は無効で、ランキング補充品はテンプレート方式を使う。

### 3.4 approve

対象: `承認待ち`。

次を順に検査する。

1. 紹介文が空でない
2. 同じURLが完了済みでない
3. 完了済みまたは承認済みの商品と「同一商品」と推定されない
4. 楽天ドメインのHTTP(S) URLである
5. 商品ページのHTTP応答が400未満

合格すると `承認済`、不合格は理由付きで `要確認` になる。

### 3.5 run

対象: `承認済`。1回の定期実行では成功1件まで。

1. シートを再読込する。
2. 完了済みURL・完了済み商品との重複を再検査する。
3. 対象行を `処理中` にし、試行回数を1増やす。
4. ledgerへ `processing` を記録する。
5. 専用Chromeで商品ページ→ROOM投稿画面へ進む。
6. 紹介文を入力し、送信する。
7. 公開my ROOMの商品数が投稿前より増えるまで再確認する。
8. 増加確認後にシートを `完了`、投稿日時をJSTで記録し、ledgerへ `posted` を追記する。
9. 投稿処理内で捕捉できた失敗はシートを `エラー` にし、ledgerへ `error` を追記する。

ログイン切れ、CAPTCHA・追加認証、または「送信後も商品数が増えない」場合は、後続商品へ進まずそのrunを止める。

強制終了、プロセスkill、マシン停止、またはSheet更新途中の異常終了は例外捕捉まで到達せず、行が `処理中` のまま、ledgerに `error` がない状態を残し得る。

## 4. シート列と状態遷移

必須列の論理順:

| 列 | 用途 |
|---|---|
| 商品URL | 楽天市場の商品ページURL |
| 紹介文 | ROOMへ入力する紹介文 |
| ステータス | パイプライン状態 |
| 投稿日時 | 完了確定時のJST日時 |
| エラー | 運用者向けの短い理由 |
| 試行回数 | 本番投稿へ進んだ回数 |

基本遷移:

```text
空欄 / 未投稿
    └─ prepare ─→ 承認待ち
                     ├─ approve合格 ─→ 承認済
                     └─ 事前検査NG ─→ 要確認

承認済
    └─ run ─→ 処理中
                  ├─ 公開商品数増加 ─→ 完了
                  └─ 投稿失敗 ─────→ エラー
```

補足:

- `要確認` と `エラー` からの自動復帰はない。人が原因を確認して適切な状態へ戻す。
- `処理中` の古い行を自動回収する仕組みはない。プロセス強制終了時は手動調査が必要。
- 現行実装に行バージョン、Compare-And-Set、シート行ロックはない。

## 5. 重複判定

現行の同一商品推定は、補充・承認・投稿直前の3段階にある。

### 判定ルール

1. 完全に同じURL
2. `item.rakuten.co.jp/<shop>/<slug>/` 形式で、同一ショップかつslug末尾の数字を除いた部分が同じ
3. 紹介文または商品タイトルの文字バイグラム・オーバーラップ係数が **0.28以上**

類似度計算前に、テンプレート定型文とフォールバック名を除去する。これにより、別商品が共通テンプレートだけで重複扱いされる誤検知を抑えている。

### 現行の境界

- `post-ledger.jsonl` を重複判定の入力として読んでいない。
- `product-url-history.txt` のような履歴正本は現行リポジトリに存在しない。
- シートから削除・移動された過去商品は、ledgerに残っていても再候補化されうる。
- URLのquery、fragment、末尾slashを統一する一般的な正規化はない。
- approveでは「完了済み＋承認済み」と比較するが、run直前の比較対象は完了済みのみ。
- プロセス間ロックがないため、同時runが同じ承認済行を選ぶ競合を防げない。

したがって「3段階重複判定あり」は正しいが、「全履歴を通して再投稿されない」は現時点では保証できない。

## 6. 景品表示法・表現安全対策

ランキング補充のテンプレート紹介文では、タイトルからクーポン、値引き、ポイント等の販促ノイズと、次のような根拠未確認の強い表現を除去する。

- No.1、1位、日本一、世界一、世界初
- 最高、最強、最安、圧倒的
- 奇跡、驚異、完璧、永久、絶対、万能、究極等

タイトルが除去で空になった場合は、一般的なフォールバック名を使う。

重要な未対応:

- 手書き紹介文には、このフィルタが適用されない。
- LLM生成文はプロンプトで誇大表現回避を指示するだけで、生成後の機械フィルタや要確認ゲートがない。
- 医療・美容・健康効果、期間限定、価格、ランキング、レビュー数など、根拠や有効期限が必要な主張を網羅的に検証しない。
- `\d+位` は「3位置調整」のような通常語まで除去しうる。

現状は「ランキング由来テンプレート文の最低限の抑制」であり、全紹介文の法令適合保証ではない。

## 7. 投稿成功の定義と照合

### 自動判定・記録・運用照合

現行コードが投稿成功と自動判定する条件は、次の2点である。

1. 投稿ボタン操作後まで例外なく進む
2. 公開my ROOMの商品数が投稿前より増加する

この判定後、コードは対象行を `完了` にして投稿日時を保存し、ledgerへ `posted` を追記する。ただし、書き込んだSheet・ledger・logを自動で再読込して相互検証する処理はない。

運用上の最終照合条件は次のとおりである。

1. 対象シート行が `完了` で、投稿日時と試行回数に矛盾がない
2. 同じ行番号・商品URL・時刻に対応するledgerの `processing → posted` がある
3. runログに対応する致命的エラーがない
4. 公開my ROOMの商品数が増えている
5. 公開my ROOMに対象商品そのものが表示されている

この5点を照合して初めて、運用上の完全な成功と扱う。

### 現行実装の限界

- コードが自動確認するのは商品数の増加であり、増えた商品が対象URLの商品かは確認しない。
- 別プロセスや手動投稿が同時刻に商品数を増やすと、誤って対象投稿成功と判定する余地がある。
- stdoutの `RunSummary`、シート `完了`、ledger `posted` のいずれか単独では成功証拠として不十分。
- ledgerにはrun_idがないため、近接する別runのイベントは行番号・URL・時刻で人が分離する必要がある。

### 推奨する照合順

```text
最終RunSummary
  → 対象シート行（状態・投稿日時・試行回数・エラー）
  → 同一行のledger processing/posted
  → post.logの該当時刻
  → 公開my ROOMの商品数増加
  → 公開my ROOM上の対象商品一致
```

## 8. dry-runの意味

`run --limit 1 --dry-run` は、商品ページと投稿画面へ進み、紹介文入力まで確認するが、送信ボタンを押さず、シート・ledgerを書き換えない。

ただし現行 `runner.py` は、dry-runでも内部の `summary.posted` を1増やす。そのため次の出力は「本番投稿成功」ではない。

```text
RunSummary(seen=1, changed=0, posted=1, errors=0)
```

ここでの `posted=1` は「送信しない投稿経路のシミュレーションが1件通った」という実装上のカウンタである。公開ROOMの商品数増加、シート完了、ledger postedは発生しない。Claude Codeで改善する際は、`would_post` や `validated` など誤解のない指標へ分離することを推奨する。

## 9. launchdとCodex automationの排他

2026-07-07にlaunchdとCodex automationが重複稼働し、1日5件投稿された事故がある。

現行の排他ルール:

- launchd `com.ynfactory.rakuten-room-post` が有効な間、Codex automationを再開しない。
- Codex automation `rakuten-room-post` と `room-20` は両方PAUSEDを維持する。
- スケジューラを切り替える場合は、旧系統の停止確認→新系統の有効化→単発監視の順に行う。
- コード上の相互排他ロックはないため、運用ルール違反を実装が防いでくれるわけではない。

Codex automationの再開、launchdのload/unload/enable/disable/kickstart、定刻変更はすべて直前の明示承認が必要。

## 10. 2026-07-27 ライブスナップショット

観測時刻: **2026-07-27 21:50〜21:55 JST**  
確認方法: シート・ledger・launchctl・Codex automation設定・専用Chrome経由の公開my ROOMを読み取り専用で照合

| 項目 | 観測値 |
|---|---|
| シートの商品行 | 68 |
| 完了 | 49 |
| 承認済 | 5 |
| 要確認 | 12 |
| エラー | 2 |
| 公開my ROOMの商品数 | 49 |
| ROOMセッション | 有効 |
| launchd | 登録済み、定刻待機のため `not running` |
| launchd累計runs | 14 |
| launchd last exit code | 0 |
| Codex `rakuten-room-post` | PAUSED |
| Codex `room-20` | PAUSED |
| 直近ledger | 7/27 12:00 row 62、20:00 row 63が各 `processing → posted` |
| テスト | 27 passed |
| シェル構文 | `run_once.sh`、`install_launchd.sh`、`start_chrome_room.sh` 合格 |
| plist構文 | post/chromeとも `plutil -lint` 合格 |
| runtime Python | 3.9.6 |

解釈:

- シート完了49件と公開my ROOM 49件は集計上整合している。
- 直近2件の `posted` は、現行コードでは公開商品数増加guardを通過した後にだけ記録される。
- ただし、このスナップショットは各49商品のURL一対一照合までは行っていない。
- `state=not running` は異常停止を意味せず、定刻間の待機状態。`last exit code=0` も外部公開成功の単独証拠にはしない。

## 11. 27テストの範囲

2026-07-27に次で再実行し、**27 passed**を確認した。

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=src \
~/rakuten-room-auto/.venv/bin/python -m pytest -q -p no:cacheprovider
```

主なカバー範囲:

- config/env展開
- replenishの閾値、件数、失敗継続、dry-run、同一商品除外
- approveの類似商品退避
- OAuth preflight失敗時に後続工程を呼ばないこと
- タイトルの販促ノイズ・誇大表現除去
- 類似度、ショップ型番違い、フォールバック誤検知回帰
- URL形式検査
- browser主要エラー文の日本語性
- Sheets列変換、行選択、試行回数、RefreshErrorの秘密情報非表示

未カバーまたは弱い範囲:

- 実Google Sheetsと楽天ROOMを組み合わせたE2E
- 同時実行・多重起動・行競合
- プロセス停止後の `処理中` 回収
- 対象商品URLの公開一致
- 手書き・LLM紹介文の後段表現検査
- ledger破損、ログローテーション、ディスク枯渇
- launchdとCodex automationの機械的排他

テスト実行時の警告:

- Python 3.9はEOL
- google-auth / google-api-coreのPython 3.9サポート警告
- LibreSSL 2.8.3に対するurllib3 v2の警告

## 12. README / AGENTS.mdと現行コード・ライブ状態の差異

| 文書上の記述 | 現状 |
|---|---|
| AGENTS.md: テスト25件 | 現行は27件 |
| AGENTS.md: 現在の状態は2026-07-07の4商品・承認済5件等 | 2026-07-27のライブ値は完了49、承認済5、要確認12、エラー2 |
| AGENTS.md: エラーメッセージはすべて日本語 | browser主要メッセージは日本語だが、`llm.py`、`sheets.py`、CLI説明等に英語が残る |
| README/AGENTS.md: 3段階の同一商品スキップ | 実装済み。ただし履歴ledgerを読まず、シート外へ消えた過去商品は保証対象外 |
| 過去運用メモ: product-url-historyとledgerを使う履歴除外 | 現行コードにはproduct-url-historyの読書きもledger横断重複判定もない |
| README: dry-runは送信しない | 正しい。ただし出力上は `posted=1` になり得る点が未説明 |
| AGENTS.md: ledger postedは商品数増加を検証済み | 正しい。ただし対象商品のURL一致までは検証しない |
| README: エラー時は失敗行をエラー状態にする | 投稿工程は該当。prepare/approveの事前検査NGは主に要確認。run_once前段は `|| true` で後続へ進む |
| AGENTS.md: 紹介文の景表法対策 | 自動ランキング補充文には実装。手書き文とLLM生成文には後段フィルタなし |
| AGENTS.md: launchdとCodex automationの排他 | ライブ設定はルールどおり。ただしコードで強制されず運用依存 |

この差異一覧を、ブラッシュアップ時の出発点とする。文書の古い数値をコード仕様と混同しないこと。

## 13. 既知の制約・リスク

1. プロセスロック・行ロックがなく、多重起動時の二重投稿リスクがある。
2. 成功判定は公開商品数増加で、対象商品一致ではない。
3. ledgerは追記のみで、run_id、ハッシュチェーン、排他、重複判定入力がない。
4. シート更新とROOM投稿はトランザクションではなく、中断点によって状態がずれる。
5. 古い `処理中` の自動回収がない。
6. URL正規化と全履歴重複排除が不足している。
7. `run_once.sh` はreplenish/prepare/approveを `|| true` で継続するため、前段異常の一部を無視してrunへ進む。
8. 手書き・LLM紹介文の表現安全ゲートが不足している。
9. Python 3.9.6 EOLとLibreSSL互換警告がある。
10. Chrome/126固定User-Agentはいずれ陳腐化する。
11. DOMテキストとボタン名に依存し、楽天側UI変更で壊れうる。
12. ランキング抽出はタイトル15文字以上等のヒューリスティックに依存する。
13. logとledgerの保持期間・ローテーション・容量監視が定義されていない。
14. CLIと一部エラーが英語で、非エンジニア運用者向け日本語方針と不一致。

## 14. 改善バックログ

### P0: 二重投稿・誤成功・法令リスクを先に閉じる

1. **単一実行ロック**  
   runtime配下のローカルロックでlaunchd、手動、Codexの同時runを拒否する。ロック所有PID・開始時刻・期限を記録する。

2. **行のclaimと冪等性キー**  
   投稿前にrun_idと対象行を原子的にclaimし、同一URL・同一行・同一runの再送を防ぐ。古い `処理中` の安全な回収手順も実装する。

3. **対象商品一致による成功判定**  
   商品数増加に加え、公開my ROOMの最新商品が対象商品コード・正規化URL・商品識別子と一致することを必須にする。

4. **全履歴重複排除**  
   正規化URLと商品識別子を、シート＋ledger＋専用履歴正本から照合する。query、fragment、末尾slashを正規化し、シートから消えた商品も除外する。

5. **全紹介文の表現安全ゲート**  
   テンプレート、手書き、LLMの全経路へ同じ後段検査を適用する。健康・美容効果、No.1、価格、期間、レビュー等の根拠必須表現は `要確認` に落とす。

6. **fail-closedな工程制御**  
   `|| true` を分類し、OAuth・シート整合・重複判定・承認工程の重大エラー時は投稿へ進まない。補充失敗だけ継続可能、など明示的なポリシーにする。

### P1: 監査性・保守性を上げる

1. ledgerへrun_id、scheduler、dry-run、本番、開始・終了、公開前後件数、対象識別子を追加する。
2. `reconcile` 読み取り専用コマンドを追加し、Sheet・ledger・log・公開ROOMの不一致を一覧化する。
3. dry-runの `posted` を `validated` / `would_post` に分離する。
4. Pythonをサポート中の版へ更新し、OpenSSL系ランタイムで依存を再固定する。
5. 全エラーを秘密情報なしの日本語へ統一する。
6. scheduler排他preflightを追加し、launchd有効時にCodex automation ACTIVEを検出したら停止する。
7. 多重起動、クラッシュ復旧、対象URL一致、手書き・LLM表現検査のテストを追加する。
8. README、AGENTS.md、CURRENT_SPEC.mdの更新責任と更新日をそろえる。

### P2: 品質・運用体験を改善する

1. User-Agent固定値を更新可能な設定またはブラウザ実値へ寄せる。
2. ランキング抽出を構造化データ優先にし、DOM変更検知と診断情報を追加する。
3. 類似度0.28を監査データで再評価し、誤検知・見逃しの記録を残す。
4. ledger/logのローテーション、容量監視、バックアップ、破損検査を追加する。
5. 読み取り専用health checkでOAuth、Sheets、Chrome CDP、ROOMセッション、scheduler排他、実行コピー同期差分をまとめて表示する。

## 15. Claude Code向け開始手順

1. JST日時をツールで確認する。
2. リポジトリルートの `AGENTS.md`、会社HANDOFF、最新日付TODOを読む。
3. この `CURRENT_SPEC.md`、`rakuten-room-auto/AGENTS.md`、`README.md` を読む。
4. `src/rakuten_room_auto/`、`scripts/run_once.sh`、launchd plist、現行testsを確認する。
5. 秘密値を出力せず、読み取り専用で以下を確認する。
   - 正本と実行コピーの差分
   - launchd状態とCodex automationsがPAUSEDであること
   - テスト件数と警告
   - 必要な場合だけSheet・ledger・公開ROOMの集計整合
6. P0/P1/P2から今回の対象を一つに絞り、要件、非対象、完了条件、ロールバックを定義する。
7. 正本だけを編集し、単体テスト・静的検査を行う。
8. 実行コピーへの同期、本番設定変更、外部状態変更の直前でオーナー承認を得る。
9. 承認後も、まずdry-runまたは読み取り専用検証、本番は最大1件、Sheet・ledger・log・公開ROOMを照合する。
10. Drive側ではGit操作しない。GitHubへ反映する場合はローカルGit作業コピーと所定の同期スクリプトを使い、push直前に改めて承認を得る。

## 16. 明示承認が必要な操作

次は、過去に包括承認があったとしても、ブラッシュアップ作業では実行直前に確認する。

- `run` の本番実行、投稿ボタン押下、公開ROOMへの送信
- `replenish`、`prepare`、`approve`、setupスクリプト等によるライブシート変更
- OAuth手動再認証、認可範囲変更、tokenファイルの手動交換・削除、API有効化、認証ファイル変更
- 専用Chromeでのログイン、追加認証、アカウント切替
- 正本からアクティブな実行コピーへのrsync
- `install_launchd.sh`、launchctlのload/unload/enable/disable/kickstart、時刻変更
- Codex automationの再開・停止・スケジュール変更
- config、環境変数、シートID・列・ステータス選択肢の変更
- `処理中`、`エラー`、`要確認`、`完了` の手動修復や一括変更
- ledger、log、履歴、Chromeプロファイル、トークンの削除・初期化
- Git push、公開、外部送信、不可逆な削除

読み取り専用のテスト、コード確認、差分確認、集計確認は、秘密情報を表示せず外部状態を変えない範囲で実行できる。

---

このシステムの本番成功は「コマンドが0終了したこと」ではなく、**対象行・同一runのledger・log・公開my ROOMを照合し、公開商品数が増え、対象商品が実際に表示されたこと**で判断する。
