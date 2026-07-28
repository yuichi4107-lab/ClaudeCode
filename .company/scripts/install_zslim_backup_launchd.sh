#!/bin/zsh
set -euo pipefail

LABEL="com.ynfactory.zslim-backup"
LOCAL_ROOT="${YNFACTORY_LOCAL_ROOT:-$HOME/YNFactory-cc}"
RUNNER="$HOME/.local/bin/ynfactory-zslim-backup.sh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs"

mkdir -p "$HOME/.local/bin" "$HOME/.ynfactory" "$HOME/Library/LaunchAgents" "$LOG_DIR"

cat > "$RUNNER" <<EOF
#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:\$HOME/.local/bin"

LOCAL_ROOT="${LOCAL_ROOT}"
RESTIC_REPO="/Volumes/ZSlim/YNFactory-backups/restic"
PASSWORD_FILE="\$HOME/.ynfactory/restic-zslim-password"
LOG_FILE="\$HOME/Library/Logs/ynfactory-zslim-backup.log"
LOCK_DIR="\$HOME/.ynfactory/zslim-backup.lock"

log() {
  printf '[%s] %s\n' "\$(date '+%Y-%m-%d %H:%M:%S %Z')" "\$*"
}

{
  log "start zslim backup"

  if ! mkdir "\$LOCK_DIR" 2>/dev/null; then
    if find "\$LOCK_DIR" -prune -mmin +720 >/dev/null 2>&1; then
      log "removing stale lock: \$LOCK_DIR"
      rm -rf "\$LOCK_DIR"
      mkdir "\$LOCK_DIR"
    else
      log "another backup appears to be running; skip"
      exit 0
    fi
  fi
  trap 'rmdir "\$LOCK_DIR" 2>/dev/null || true' EXIT

  if [ ! -d "/Volumes/ZSlim" ]; then
    log "ZSlim is not mounted; skip"
    exit 0
  fi

  if [ ! -f "\$RESTIC_REPO/config" ]; then
    log "restic repo is not available at \$RESTIC_REPO; skip"
    exit 0
  fi

  if [ ! -f "\$PASSWORD_FILE" ]; then
    log "password file is missing: \$PASSWORD_FILE"
    exit 1
  fi

  if [ ! -d "\$LOCAL_ROOT/.git" ]; then
    log "local Git root is missing: \$LOCAL_ROOT"
    exit 1
  fi

  cd "\$LOCAL_ROOT"

  if [ "\${1:-}" = "--dry-run" ] || [ "\${YNFACTORY_ZSLIM_BACKUP_DRY_RUN:-}" = "1" ]; then
    log "running backup dry-run"
    python3 .company/scripts/backup_zslim_restic.py backup --dry-run
  else
    log "running backup + retention + check"
    python3 .company/scripts/backup_zslim_restic.py run
  fi

  log "finished zslim backup"
} >> "\$LOG_FILE" 2>&1
EOF

chmod 700 "$RUNNER"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-lc</string>
        <string>$RUNNER</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/ynfactory-zslim-backup-launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/ynfactory-zslim-backup-launchd.err</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST"

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl print "gui/$(id -u)/$LABEL" >/dev/null

echo "installed: $PLIST"
echo "runner:    $RUNNER"
echo "schedule:  daily 03:00"
