#!/bin/bash
# VPS上で実行: cron登録（多重登録防止つき）。VPSはJST前提。
set -e
LOG=/opt/quant-bot/state
mkdir -p "$LOG"
TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v "quant-bot" > "$TMP" || true
cat >> "$TMP" << 'CRON'
# quant-bot: RSI2シグナル(米国クローズ後 06:15 JST) / ベーシス監視(09:30 JST)
15 6 * * 2-6 cd /opt/quant-bot && /usr/bin/python3 run_daily.py rsi2 >> state/rsi2.log 2>&1
30 9 * * * cd /opt/quant-bot && /usr/bin/python3 run_daily.py basis >> state/basis.log 2>&1
CRON
crontab "$TMP"
rm "$TMP"
echo "cron installed:"
crontab -l | grep quant-bot
