#!/bin/bash
set -euo pipefail

# Only run in remote (web) environment
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Install Python dependencies
pip install -r "$CLAUDE_PROJECT_DIR/requirements.txt"

# Install dev dependencies (pytest for testing, flake8 for linting)
pip install pytest flake8

# Set PYTHONPATH for the session
echo 'export PYTHONPATH="."' >> "$CLAUDE_ENV_FILE"
