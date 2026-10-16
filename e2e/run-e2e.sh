#!/usr/bin/env bash
# Provision an isolated database, seed it, start backend + frontend, run Playwright, stop servers.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
export POSTGRES_DB="${E2E_DB:-plantops_e2e}" PLANTOPS_DEMO_MODE=true DJANGO_DEBUG=true
# The suite signs in more than 10 times a minute; relax the login throttle for this isolated run only.
export PLANTOPS_LOGIN_RATE="${PLANTOPS_LOGIN_RATE:-1000/min}"
PY="${PYTHON:-python}"
cd "$ROOT/backend"
$PY manage.py migrate --noinput >/dev/null
$PY manage.py seed_demo --reset --days 30 --seed 7
$PY manage.py runserver 127.0.0.1:8001 --noreload >"$HERE/backend.log" 2>&1 &
BACK=$!
cd "$ROOT/frontend"
PLANTOPS_API_URL=http://127.0.0.1:8001 npx vite --host 127.0.0.1 --port 5174 --strictPort >"$HERE/frontend.log" 2>&1 &
FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do curl -sf http://127.0.0.1:5174/api/auth/csrf/ >/dev/null && break; sleep 1; done
cd "$HERE"
E2E_BASE_URL=http://127.0.0.1:5174 npx playwright test "$@"
