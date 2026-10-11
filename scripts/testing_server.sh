#!/usr/bin/env bash
# Local testing launcher — starts GuardLens detached.
# Secrets are loaded from a gitignored .env file (never pass keys on the CLI).
# Create .env with:  GUARDLENS_NVIDIA_API_KEY=nvapi-xxxx
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a || true
for p in $(pgrep -f 'python -m guardlens' || true); do kill -9 "$p" 2>/dev/null || true; done
for _ in $(seq 1 40); do ss -ltnp 2>/dev/null | grep -qE ':8090|:8443' || break; sleep 0.3; done
setsid env \
  GUARDLENS_HOST=0.0.0.0 GUARDLENS_PORT="${GUARDLENS_PORT:-8090}" \
  GUARDLENS_SSL_CERTFILE="${GUARDLENS_SSL_CERTFILE:-}" \
  GUARDLENS_SSL_KEYFILE="${GUARDLENS_SSL_KEYFILE:-}" \
  GUARDLENS_PUBLIC_URL="${GUARDLENS_PUBLIC_URL:-}" \
  GUARDLENS_NVIDIA_API_KEY="${GUARDLENS_NVIDIA_API_KEY:-}" \
  .venv/bin/python -m guardlens > data/testing-server.log 2>&1 < /dev/null &
disown || true
sleep 1
pgrep -f 'python -m guardlens' | head -1 > data/testing-server.pid
echo "started pid=$(cat data/testing-server.pid)  port=${GUARDLENS_PORT:-8090}  tls=$([ -n "${GUARDLENS_SSL_CERTFILE:-}" ] && echo on || echo off)"
