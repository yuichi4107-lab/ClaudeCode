#!/usr/bin/env bash
# Install cron job on the VPS for periodic sync.
# Run on the VPS as the user that owns /opt/notebooklm-sync (typically root).
set -euo pipefail

PROJECT_DIR="/opt/notebooklm-sync"
PY="${PROJECT_DIR}/.venv/bin/python"
CRON_LINE="*/30 * * * * cd ${PROJECT_DIR} && ${PY} src/sync.py >> ${PROJECT_DIR}/logs/sync_cron.log 2>&1"
LOGROTATE_FILE="/etc/logrotate.d/notebooklm-sync"

echo "[INFO] Installing cron job..."
( crontab -l 2>/dev/null | grep -v "${PROJECT_DIR}/src/sync.py" ; echo "${CRON_LINE}" ) | crontab -

echo "[INFO] Current crontab:"
crontab -l | grep -F "${PROJECT_DIR}" || true

echo ""
echo "[INFO] Installing logrotate config at ${LOGROTATE_FILE}..."
cat > "${LOGROTATE_FILE}" <<EOF
${PROJECT_DIR}/logs/*.log {
    daily
    rotate 14
    maxsize 50M
    compress
    missingok
    notifempty
    copytruncate
}
EOF

echo "[INFO] logrotate config installed. Verifying syntax..."
logrotate -d "${LOGROTATE_FILE}" 2>&1 | tail -5 || true

echo ""
echo "[DONE] cron job + logrotate installed."
echo "       Logs: tail -f ${PROJECT_DIR}/logs/sync_cron.log"
