# autorace_evaluator

南関東圏外の5場(川口・伊勢崎・浜松・山陽・飯塚)を対象としたオートレース選手能力評価システム。
autorace.jp からレース結果をスクレイピングして SQLite に蓄積し、3つの統計的指標で選手の
「地力」を縮約したスコアとして提示する。

## システム概要

### 3指標の定義と解釈

**整備力 (maintenance_score)**
同一節(開催)内・良走路同士に限定した「前日比の試走タイム差」
(`diff = 前日の試走タイム − 当日の試走タイム`)を選手ごとに集計したもの。
正の値が大きいほど、開催が進むにつれて機材のコンディションを上げてこられている
(整備で機材を仕上げてくる)選手と解釈できる。1日でも開催に穴が空くと別節扱いになるため、
順延・中止をまたいだペアは作らない(安全側)。`n_pairs`(前日ペア数)が
`MIN_PAIRS`(既定5)未満の選手は参考値としてスコアを NaN にする。

**スタート力 (start_score)**
ST(スタートタイミング)の基礎統計と、「ダッシュ力」という統計的プロキシを合成したもの。
ダッシュ力は `early_loss = per100m(競走タイム) − per100m(上がりタイム)` (静止発進〜序盤で
失った時間)を、レース内センタリング後に ST・機材速度(試走タイム)・ハンデで Ridge 回帰
した残差として推定する。同条件の他選手と比べて残差が小さい(＝序盤ロスが少ない)ほど
「ダッシュ力あり」と評価し、符号を反転・経験ベイズ縮約(サンプル数が少ない選手を全体平均へ
寄せる)した値が `dash` 列になる。ST の平均は少数出走の極端値を避けるため同様に縮約する。
`n_st` が `MIN_RACES`(既定10)未満の選手は参考値。

**突っ込み度 (attack_score)**
「前に車がいる展開で日和らず突っ込めているか」の統計的プロキシ。2つの成分から成る。
(a) 混戦時パフォーマンス: 試走タイム・ハンデから期待される着順との残差を、前に1台以上いる
レースに限定して集計(`attack_a`)。ST を説明変数に含めないのは、スタートで稼ぐ成分ではなく
「前を差す・突っ込む」成分を残差に残すため。
(b) 重ハン時の追い抜き量: `passed = 前にいた車数 − 先着された車数`(`mean_passed`)。
後ろから差されるとマイナスに効くのは仕様(日和って抜かれる選手を低評価にする)。
参考指標として事故率・違反率(`accident_rate` / `violation_rate`)も併記する。
`n_attack_a` と `n_overtake` の大きい方が `MIN_RACES` 未満の選手は参考値。

**総合スコア (total_score)**
上記3スコアのうち NaN でないものだけの単純平均。何本のスコアが有効かは `n_valid_scores`
列に出る(0〜3)。3指標とも NaN の選手は `total_score` も NaN になり、レポート末尾に回る。

## セットアップ

```bash
pip install -e .
# or
pip install -r requirements.txt
```

新規の外部依存は追加していない(pandas / numpy / scikit-learn / beautifulsoup4 / lxml /
colorama は既存の requirements.txt に含まれる)。

## コマンド例

```bash
# レース結果を収集(会場・期間はオプション)
autorace scrape --from-date 2026-01-01 --to-date 2026-07-01
autorace scrape --date 20260212 --venue kawaguchi

# 出走表(車級・期別・級班・年齢・連対率)を収集して race_entries に付与
# ※結果収集が先。races テーブルに保存済みのレースだけが対象になる
autorace scrape-program --from-date 2026-01-01 --to-date 2026-07-01

# 選手能力評価(整備力・スタート力・突っ込み度の統合レポート)
autorace evaluate --from-date 2026-01-01 --to-date 2026-07-01
autorace evaluate --from-date 2026-01-01 --to-date 2026-07-01 --venue kawaguchi --top 30
autorace evaluate --from-date 2026-01-01 --to-date 2026-07-01 --player 12345
autorace evaluate --from-date 2026-01-01 --to-date 2026-07-01 --csv data/reports/my_report.csv
autorace evaluate --from-date 2026-01-01 --to-date 2026-07-01 --include-retrial

# dumpしたAPI応答JSONをパースして確認(選手能力評価の元データを1件ずつ検証したい場合)
autorace parse-json path/to/xxx.result.json
autorace parse-json path/to/xxx.result.json --json
autorace parse-json path/to/xxx.result.json --save   # パース結果をDBへ保存
```

`evaluate` は DB(既定 `data/autorace.db`)が存在しない場合、先に `scrape` または
`parse-json --save` でデータを投入するようエラーメッセージを出して終了する。
CSV の既定出力先は `data/reports/autorace_eval_{from}_{to}[_{venue}].csv`
(`--csv` で明示指定も可能)。

## データ取得の仕組み(実サイト検証済み)

**autorace.jp の結果ページHTMLはJS描画のシェルであり、レース結果データを含まない**
(2026-07 に実ページで確認)。データは以下の JSON API から取得する。

- `POST /race_info/RaceResult` `{placeCode, raceDate: "YYYY-MM-DD", raceNo}`
  → 着順・車番・選手(登録番号/氏名)・ハンデ・試走タイム(再試走コード)・競走タイム・
  ST・事故名・スタート反則コード・払戻(refundInfo)
- `POST /race_info/OtherRaceInfo`(同パラメータ)
  → 距離・天候・気温・走路温度・走路状況コード(試走時/競走時)・節の開始/終了日・レース名
- `GET /race_info/XML/Calendar?date=YYYY-MM`
  → 会場ごとの開催日と最終レース番号(開催日の事前絞り込みに使用)

POST は Laravel の CSRF 保護下にあるため、`scraper/base.py` がHTMLシェルから
`csrf-token` メタタグを取得し `X-CSRF-TOKEN` ヘッダ付きで送信する(419 時は自動再取得)。
API の `Failure` コードは 4101=データなし(未開催・存在しないレース番号)、4200=開催中止。
1レースあたり2リクエスト、レート制限は3秒+ジッター。

- 走路状況コード: 0=良走路, 1=湿走路, 5=斑走路(保守的に湿扱い), 2=風, 3=オイル, 4=荒。
  競走時の状況を `races.track_status`、試走時を `races.trial_track_status` に保存し、
  整備力(試走タイム比較)は試走時の走路状況で「良走路」判定する。
- 節ID(meeting_id)は API の `periodStartDate` から `{venue}_{節初日}` を直接保存する
  (evaluate 時の日付連続性による導出は meeting_id 欠損行のみに適用)。
- **上がりタイム(last_lap_time)は API に掲載されないため常に NULL**。スタート力の
  「ダッシュ力」成分はサンプル0となり、STベースの成分のみでスコアが計算される(設計上の
  グレースフルデグラデーション)。
- **競走タイムの単位は per-100m 換算で確認済み**(実データ例: raceTime=3.852, 距離3100m)。
  `TIME_FORMAT = "per100m"` のままでよい。

API仕様が変わった場合は `parsers/selectors.py` の対応表を修正し、実応答JSONを
`tests/fixtures/autorace/real/{venue}_{YYYY-MM-DD}_{race_no}.result.json` /
`.other.json` の命名で置いて `python -m pytest tests/ -q` で検証する。
`autorace scrape --dump-html DIR` で取得応答を可読名でdumpし、
`autorace parse-json DIR/xxx.result.json` で1件ずつパース結果を確認できる。

## スコアの読み方

- 各スコアは `zscore`(平均0・標準偏差1への標準化)ベースなので、0 が「平均的」、
  プラスが平均より上、マイナスが平均より下という相対評価になる。実数の大小に絶対的な
  意味はない(母集団=指定期間・会場の全出走選手が変わればスコアも変わる)。
- `n_pairs`(整備力)が `MIN_PAIRS` 未満、`n_st` / `n_attack_a` / `n_overtake`
  (スタート力・突っ込み度)が `MIN_RACES` 未満の選手は、サンプル不足のため該当スコアが
  NaN になる「参考行」として扱われる。総合スコアも NaN 個数に応じて有効な指標だけの
  平均になる(`n_valid_scores` 列で本数を確認できる)。
- `--player` で選手を1人指定すると、その選手の全列に加えて各スコアの母集団内での
  順位(rank)・百分位(pct)が表示される。
- `--include-retrial` を付けると、再試走マーク付きの試走タイムも整備力の集計対象に含める
  (既定では除外)。

## 湿走路(雨)適性 wet_score(参考列)

湿走路レースだけで学習した期待着順モデル(試走タイム+ハンデ、レース内センタリング+Ridge)
に対する残差の選手平均(縮約k=5)を標準化したものが `wet_score`。`wet_gap` は良走路での
同じ推定値との差で、正なら「良走路の自分より雨で走る」雨巧者を意味する(推定誤差の差で
ノイジーなため生値のまま)。`n_wet`(湿走路出走数)が `MIN_WET_RACES`(既定5)未満は NaN。
**総合スコア(3指標平均)には含めない**: 湿走路は全体の約2割で欠損選手が多く、含めると
選手ごとに total_score の意味(何指標の平均か)が変わること、突っ込み度と同じ残差構成で
二重計上になること、雨適性は当日の走路状態に依存する条件付き情報であることが理由。

## 新人(2級車)成績レポート(別CSV)

`scrape-program` で車級・期別を収集済みの場合、`evaluate` が
`autorace_rookie_{from}_{to}.csv` を自動出力する。2級車出走行(全選手が2級車で
デビューし昇級で1級車へ移る)を新人期間の操作的定義とし、期別がデータ内最新
`ROOKIE_RECENT_TERMS`(既定2)期以内、またはDB内初出走から `ROOKIE_MAX_RACES`
(既定30)走以内の選手をロースターとする(判定根拠は `definition` 列)。
指標: 全選手・良走路で学習済みの期待着順残差を新人×2級車行に絞って縮約した
`rookie_attack`(少数サンプルでモデルを学習し直さない)、2級車行の平均ST
(`st_gap_vs_field` = 全体平均との差)、試走タイム推移の傾き `trial_trend`
(負=機材・乗り手が仕上がってきている)、勝率・3着内率。`rookie_score` は
新人母集団内での標準化平均。

## 週次自動更新(GitHub Actions)

`.github/workflows/autorace-weekly.yml` が毎週月曜 06:00 JST に実行される
(手動実行は Actions タブの workflow_dispatch)。処理は
`scripts/autorace_weekly_update.py`(LLM不使用の純Python):

1. orphan branch `autorace-data` から `autorace.db.gz` を復元
2. 収集窓 = 前回最終収集日−2日 〜 昨日。`clear_recent_not_found` で
   「結果未確定のうちにデータなし応答を踏んだレース」を再チェック対象に戻す
3. `scrape` → `scrape-program` を差分実行(HTTPキャッシュは使わず scrape_log で差分判定)
4. 直近365日ローリングで evaluate し、以下を main に差分コミットする:
   - `data/reports/autorace_eval_latest.csv` / `autorace_rookie_latest.csv` —
     **常に最新版**(予想機能はこちらを参照する)
   - `data/reports/archive/autorace_{eval,rookie}_{評価末日}.csv` —
     週ごとのスナップショットを**上書きせず蓄積**(指標の推移分析・
     予想モデルの時点別バックテストに使える)
5. DBを gzip して autorace-data ブランチへ単一コミット force-push(履歴が太らない)

初回は手元のDBを一度だけ種蒔きする:

```bash
gzip -9 -c data/autorace.db > /tmp/autorace.db.gz
BLOB=$(git hash-object -w /tmp/autorace.db.gz)
TREE=$(printf '100644 blob %s\tautorace.db.gz\n' "$BLOB" | git mktree)
git push -f origin "$(git commit-tree "$TREE" -m 'initial db snapshot')":refs/heads/autorace-data
```

## 予想機能ロードマップ(未実装)

各選手×レースの特徴量として、本システムの4指標(整備力・スタート力・突っ込み度・
雨適性 — 当日の走路状態で wet_score / mean_st_wet を切り替え)+出走表由来の属性
(級班・期別・rate2/3・年齢)+直近フォーム(直近10走の期待着順残差移動平均・
当該会場成績)を組み、LightGBM のランキング学習(lambdarank, group=race_id)で
着順確率を推定する。レース内で正規化した確率を Harville 近似
P(i→1着)×P(j→2着|i除外) で2連単の組合せ確率に合成し、収集済み payouts テーブルと
突き合わせて「予測確率×払戻 > 閾値」の期待値ベット戦略を時系列ウォークフォワード
(学習=過去9か月、検証=直近3か月)で ROI バックテストする。データは既に
races / race_entries / payouts に揃っており、新規収集は不要。
