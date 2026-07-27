#!/bin/bash
# VPS上で実行: keibaシステムの.envからTelegram設定を流用して /opt/quant-bot/.env を生成
set -e
SRC=/opt/keiba-unified/keiba-ai-system/.env
DST=/opt/quant-bot/.env
if [ -f "$DST" ]; then
  echo ".env already exists, skip"
  exit 0
fi
grep -E '^TELEGRAM_(BOT_TOKEN|CHAT_ID)=' "$SRC" > "$DST"
chmod 600 "$DST"
echo "created $DST"
