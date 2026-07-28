#!/usr/bin/env bash
# Claude Code Channels (Telegram) リセットスクリプト
set -u
echo "==========================================="
echo "Claude Code Telegram Channel リセットト"
echo "==========================================="
TG_DIR="$HOME/.claude/channels/telegram"
echo ""
echo "[1/4] 現状確認: $TG_DIR"
if [ -d "$TG_DIR" ]; then
  ls -la "$TG_DIR" 2>/dev/null || echo "  (空 or アクセス不可)"
else
  echo "  ディレクトリが存在しません（初回設定状態）"
fi
echo ""
echo "[2/4] ペアリング情報・トークンを削除"
for f in .env state.json access.json; do
  if [ -f "$TG_DIR/$f" ]; then
    rm -f "$TG_DIR/$f"
    echo "  削除: $f"
  else
    echo "  スキップ: $f"
  fi
done
echo ""
echo "[3/4] ゾンビプロセスを確認"
PIDS=$(ps aux | grep -E "claude|bun.*telegram" | grep -v grep | awk '{print $2}')
if [ -n "$PIDS" ]; then
  echo "  検出されたプロセス:"
  ps aux | grep -E "claude|bun.*telegram" | grep -v grep
  echo ""
  read -p "  これらを停止しますか？ [y/N]: " yn
  if [[ "$yn" =~ ^[Yy]$ ]]; then
    echo "$PIDS" | xargs -I {} kill {} 2>/dev/null
    sleep 1
    echo "  停止しました。残存プロセス:"
    ps aux | grep -E "claude|bun.*telegram" | grep -v grep || echo "    なし"
  else
    echo "  停止をスキップ"
  fi
else
  echo "  関連プロセスは動作していません"
fi
echo ""
echo "[4/4] Bun動作確認"
if command -v bun >/dev/null 2>&1; then
  echo "  bun $(bun --version) OK"
else
  echo "  bun が未インストールです"
  echo "  curl -fsSL https://bun.sh/install | bash"
fi
echo ""
echo "==========================================="
echo "リセット完了 — 次は Claude Code 内の手順へ"
echo "==========================================="
