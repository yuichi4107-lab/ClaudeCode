#!/bin/bash
# OpenClaw + MCP Agent Team セットアップスクリプト
# 
# 使い方:
#   1. API キーを環境変数にセット
#   2. このスクリプトを実行
#
# 必要な環境変数:
#   ANTHROPIC_API_KEY  - Anthropic API キー (Claude Sonnet/Haiku 用)
#   OPENAI_API_KEY     - OpenAI API キー (GPT-4.1 / Codex 用)
#   GOOGLE_AI_API_KEY  - Google AI API キー (Gemini 用)
#   GITHUB_TOKEN       - GitHub トークン (オプション、MCP用)

set -euo pipefail

echo "=== OpenClaw Agent Team Setup ==="
echo ""

# 1. OpenClaw インストール確認
if ! command -v openclaw &> /dev/null; then
    echo "[1/6] Installing OpenClaw..."
    npm install -g openclaw
else
    echo "[1/6] OpenClaw already installed: $(openclaw --version)"
fi

# 2. デフォルトモデル設定
echo "[2/6] Setting default models..."
openclaw models set anthropic/claude-sonnet-4-6
openclaw models set-image google/gemini-2.5-pro
openclaw models fallbacks add anthropic/claude-haiku-4-5

# 3. API キー設定
echo "[3/6] Configuring API keys..."

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    echo "$ANTHROPIC_API_KEY" | openclaw models auth paste-token --provider anthropic 2>/dev/null || \
        echo "  -> Anthropic: set manually via 'openclaw models auth add'"
else
    echo "  -> ANTHROPIC_API_KEY not set. Run: openclaw models auth add"
fi

if [ -n "${OPENAI_API_KEY:-}" ]; then
    echo "$OPENAI_API_KEY" | openclaw models auth paste-token --provider openai 2>/dev/null || \
        echo "  -> OpenAI: set manually via 'openclaw models auth add'"
else
    echo "  -> OPENAI_API_KEY not set. Run: openclaw models auth add"
fi

if [ -n "${GOOGLE_AI_API_KEY:-}" ]; then
    echo "$GOOGLE_AI_API_KEY" | openclaw models auth paste-token --provider google 2>/dev/null || \
        echo "  -> Google: set manually via 'openclaw models auth add'"
else
    echo "  -> GOOGLE_AI_API_KEY not set. Run: openclaw models auth add"
fi

# 4. エージェント追加
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "[4/6] Creating agents..."

declare -A AGENT_MODELS=(
    ["orchestrator"]="anthropic/claude-sonnet-4-6"
    ["coder"]="openai/gpt-4.1"
    ["analyst"]="anthropic/claude-haiku-4-5"
    ["scraper"]="anthropic/claude-haiku-4-5"
    ["creative"]="google/gemini-2.5-pro"
)

declare -A AGENT_NAMES=(
    ["orchestrator"]="Director"
    ["coder"]="Coder"
    ["analyst"]="Analyst"
    ["scraper"]="Scraper"
    ["creative"]="Creative"
)

declare -A AGENT_EMOJIS=(
    ["orchestrator"]="🎯"
    ["coder"]="💻"
    ["analyst"]="📊"
    ["scraper"]="🕷️"
    ["creative"]="🎨"
)

for agent in orchestrator coder analyst scraper creative; do
    WORKSPACE="$PROJECT_DIR/agents/$agent"
    mkdir -p "$WORKSPACE"
    
    # Skip if already exists
    if openclaw agents list 2>/dev/null | grep -q "^- $agent"; then
        echo "  -> $agent already exists, skipping"
    else
        openclaw agents add "$agent" \
            --workspace "$WORKSPACE" \
            --model "${AGENT_MODELS[$agent]}" \
            --non-interactive
    fi
    
    openclaw agents set-identity \
        --agent "$agent" \
        --name "${AGENT_NAMES[$agent]}" \
        --emoji "${AGENT_EMOJIS[$agent]}"
done

# 5. 設定バリデーション
echo "[5/6] Validating config..."
openclaw config validate

# 6. 完了サマリー
echo ""
echo "[6/6] Setup complete!"
echo ""
echo "=== Agent Team ==="
openclaw agents list
echo ""
echo "=== Models ==="
openclaw models status
echo ""
echo "=== Next Steps ==="
echo "  1. Set API keys:  openclaw models auth add"
echo "  2. Start gateway:  openclaw gateway"
echo "  3. Open dashboard: openclaw dashboard"
echo "  4. Test agent:     openclaw agent --agent orchestrator --message 'Hello'"
echo ""
echo "  Cron jobs (disabled by default):"
echo "    openclaw cron add --agent scraper --schedule '0 6 * * *' --message '本日の出馬表を取得'"
echo "    openclaw cron add --agent analyst --schedule '30 6 * * *' --message '本日の予想を実行'"
echo "    openclaw cron add --agent scraper --schedule '0 21 * * *' --message 'レース結果を取得'"
echo "    openclaw cron add --agent analyst --schedule '30 21 * * *' --message 'ROIレポートを作成'"
