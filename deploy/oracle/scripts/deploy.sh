#!/usr/bin/env bash
#
# Update flow: pull latest code, refresh deps, restart. Migrations run on the
# api start (ExecStartPre = 'alembic upgrade head'), so no separate migrate step.
#
# Usage (on the VM, as 'ubuntu'):  ./deploy.sh
set -euo pipefail

APP_DIR="/home/ubuntu/cpa"
BRANCH="${BRANCH:-claude/cpa-api-oracle-migration-BqigD}"

cd "${APP_DIR}"
echo "==> Pull ${BRANCH}"
git fetch origin "${BRANCH}"
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

echo "==> API deps (editable install tracks source; re-run picks up dependency changes)"
"${APP_DIR}/.venv/bin/pip" install -e . --upgrade

echo "==> Restart API (runs migrations via ExecStartPre)"
sudo systemctl restart cpa-api

echo "==> Web deps + rebuild + restart"
cd "${APP_DIR}/web"
pnpm install --frozen-lockfile
pnpm build
sudo systemctl restart cpa-web

echo "==> Local health checks"
sleep 3
curl -fsS http://127.0.0.1:8000/healthz && echo
curl -fsS http://127.0.0.1:3000/api/health && echo
echo "==> deploy complete."
