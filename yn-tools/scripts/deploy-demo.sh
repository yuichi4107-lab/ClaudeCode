#!/usr/bin/env bash
# Demo redeploy on ConoHa VPS.
# Run from /opt/yn-tools-demo (or wherever the demo checkout lives).
set -euo pipefail

cd "$(dirname "$0")/.."

git pull --ff-only

# Always rebuild — restart alone won't pick up code changes baked via Dockerfile COPY.
docker compose -f docker-compose.demo.yml up -d --build --force-recreate

docker compose -f docker-compose.demo.yml ps
docker compose -f docker-compose.demo.yml logs --tail=80 app
