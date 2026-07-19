#!/bin/bash
# 全5場×直近1年(2025-07-19〜2026-07-18)のオートレース結果を月単位で収集する。
# レート制限(3秒+ジッター)は autorace_evaluator 側の設定のまま変更しない。
# 失敗した月があっても続行する(キャッシュ+scrape_logにより再実行は差分のみ)。
set -u
cd "$(dirname "$0")/.."

LOG=data/scrape_year.log
mkdir -p data

RANGES=(
  "2025-07-19 2025-07-31"
  "2025-08-01 2025-08-31"
  "2025-09-01 2025-09-30"
  "2025-10-01 2025-10-31"
  "2025-11-01 2025-11-30"
  "2025-12-01 2025-12-31"
  "2026-01-01 2026-01-31"
  "2026-02-01 2026-02-28"
  "2026-03-01 2026-03-31"
  "2026-04-01 2026-04-30"
  "2026-05-01 2026-05-31"
  "2026-06-01 2026-06-30"
  "2026-07-01 2026-07-18"
)

echo "=== year scrape started: $(date -Is) ===" >> "$LOG"
for range in "${RANGES[@]}"; do
  set -- $range
  echo "--- chunk $1 .. $2 : $(date -Is) ---" >> "$LOG"
  python -m autorace_evaluator.cli.main scrape --from-date "$1" --to-date "$2" >> "$LOG" 2>&1
  echo "--- chunk $1 .. $2 done (exit=$?) : $(date -Is) ---" >> "$LOG"
done
echo "=== year scrape finished: $(date -Is) ===" >> "$LOG"
