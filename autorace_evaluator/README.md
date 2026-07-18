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

# 選手能力評価(整備力・スタート力・突っ込み度の統合レポート)
autorace evaluate --from-date 2026-01-01 --to-date 2026-07-01
autorace evaluate --from-date 2026-01-01 --to-date 2026-07-01 --venue kawaguchi --top 30
autorace evaluate --from-date 2026-01-01 --to-date 2026-07-01 --player 12345
autorace evaluate --from-date 2026-01-01 --to-date 2026-07-01 --csv data/reports/my_report.csv
autorace evaluate --from-date 2026-01-01 --to-date 2026-07-01 --include-retrial

# ローカルHTMLファイルをパースして確認(選手能力評価の元データを1件ずつ検証したい場合)
autorace parse-html path/to/result.html
autorace parse-html path/to/result.html --json
autorace parse-html path/to/result.html --save   # パース結果をDBへ保存
```

`evaluate` は DB(既定 `data/autorace.db`)が存在しない場合、先に `scrape` または
`parse-html --save` でデータを投入するようエラーメッセージを出して終了する。
CSV の既定出力先は `data/reports/autorace_eval_{from}_{to}[_{venue}].csv`
(`--csv` で明示指定も可能)。

## 実環境移行手順(重要)

**この開発環境からは autorace.jp に接続できないため、実HTMLでの検証は一切行えていない。**
`parsers/selectors.py` のセレクタ・見出し対応表は、tests/fixtures/autorace/synthetic_result.html
(想定DOM構造に基づく合成HTML)だけを頼りに実装している。実運用に載せる前に、必ず以下の
手順で実HTMLに合わせ込むこと。

1. ブラウザで autorace.jp の RaceResult ページ(1レース分)を「名前を付けて保存」し、
   HTML ファイルとしてローカルに置く。
2. `autorace parse-html <保存したファイル>` を実行し、末尾に出る `警告` の件数と内容を確認する。
   - `結果テーブルが見つかりません` / `car_no 列を解決できません` のような致命的な警告が
     出た場合、そのHTMLは解析不能(セレクタが根本的に合っていない)。
   - `見出し不明` や `気象ラベル不明` の警告は個別列だけが解決できていない状態。
3. 警告が出た場合、`parsers/selectors.py` の該当定数を実HTMLのDOM構造に合わせて修正する。
   - `SELECTORS`(`result_table` / `race_header` / `weather_block` / `payout_table` の
     CSSセレクタ)を実際のクラス名・タグ構造に合わせる。
   - `HEADER_FIELD_MAP` / `WEATHER_FIELD_MAP`(見出しラベルの同義語リスト)に、実HTMLで
     使われている表記(全角/半角、送り仮名の違いなど)を追加する。
   - `parsers/normalize.py` や `metrics/*.py` など、上記以外のファイルは変更しないこと。
     セレクタ・見出し対応だけで吸収できるように設計されている。
4. 修正後、実HTMLを `tests/fixtures/autorace/real/{venue}_{YYYY-MM-DD}_{race_no}.html`
   という命名で配置し、`python -m pytest tests/ -q` を実行する。
   `test_result_parser.py::test_real_fixtures_parse_without_error` がこのファイルを自動的に
   拾って「例外なくパースできる」ことを検証する(複数レース分置くほど良い)。
5. パースが安定したら `autorace scrape --date YYYYMMDD --dump-html DIR` のように
   `--dump-html` を付けて少量の日付だけ実際にスクレイピングし、取得したHTMLが想定通り
   パースできるか(warnings が出ないか)を再確認する。
6. 問題なければ本取得(`--dump-html` を外した通常の `scrape`)に進む。

**競走タイムの単位に注意**: `config/settings.py` の `TIME_FORMAT` は既定で `"per100m"`
(100mあたり換算タイムがそのまま掲載されている前提)になっている。実HTMLを確認した結果、
競走タイム・上がりタイムが「100mあたり」ではなく「その距離を走り切った総所要時間」で
掲載されていた場合は、`TIME_FORMAT` を `"total"` に変更する。`metrics/common.py` の
`to_per100m()` がこの設定を見て自動的に距離換算するため、`metrics/*.py` 側の変更は不要。

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
