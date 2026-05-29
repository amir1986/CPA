#!/usr/bin/env bash
#
# One-time provisioning for the CPA app on an OCI Always Free ARM (Ampere A1)
# Ubuntu VM. Run as the 'ubuntu' user. Safe to re-run.
#
# PREREQUISITE: create the two env files FIRST (this script never writes secrets):
#   /home/ubuntu/cpa/.env       from deploy/oracle/env/cpa-api.env.example
#   /home/ubuntu/cpa/web/.env   from deploy/oracle/env/cpa-web.env.example
# (The repo is cloned by this script, so clone once by hand to get the templates,
#  or scp the env files in, then re-run.)
#
# Override defaults via env:  REPO_URL=... BRANCH=... ./bootstrap.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/amir1986/CPA.git}"
BRANCH="${BRANCH:-claude/cpa-api-oracle-migration-BqigD}"
APP_DIR="/home/ubuntu/cpa"

echo "==> System update"
sudo apt-get update
sudo apt-get upgrade -y

echo "==> Base packages"
sudo apt-get install -y git curl ca-certificates build-essential nginx \
  software-properties-common netfilter-persistent iptables-persistent

echo "==> Python 3.12 (exact pin; deadsnakes makes it work on any Ubuntu release)"
if ! command -v python3.12 >/dev/null 2>&1; then
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt-get update
fi
sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
python3.12 --version

echo "==> Node.js 22 (NodeSource, arm64) + pnpm via corepack"
if ! command -v node >/dev/null 2>&1 || [ "$(node -v | cut -d. -f1)" != "v22" ]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
node -v
sudo corepack enable
sudo corepack prepare pnpm@10.33.0 --activate
pnpm -v

echo "==> Clone or update repo into ${APP_DIR}"
if [ ! -d "${APP_DIR}/.git" ]; then
  git clone --branch "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
else
  git -C "${APP_DIR}" fetch origin "${BRANCH}"
  git -C "${APP_DIR}" checkout "${BRANCH}"
  git -C "${APP_DIR}" pull --ff-only origin "${BRANCH}"
fi
cd "${APP_DIR}"

echo "==> Verify env files exist (this script does NOT create them)"
if [ ! -f "${APP_DIR}/.env" ]; then
  echo "MISSING ${APP_DIR}/.env  -> copy deploy/oracle/env/cpa-api.env.example and fill it"; exit 1
fi
if [ ! -f "${APP_DIR}/web/.env" ]; then
  echo "MISSING ${APP_DIR}/web/.env -> copy deploy/oracle/env/cpa-web.env.example and fill it"; exit 1
fi
chmod 600 "${APP_DIR}/.env" "${APP_DIR}/web/.env"
[ -f "${APP_DIR}/ollama_keys.txt" ] && chmod 600 "${APP_DIR}/ollama_keys.txt" || true

echo "==> Python venv + editable install (core deps only, matches Render)"
python3.12 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -e .

echo "==> Web install + build (NEXT_PUBLIC_* are inlined here)"
cd "${APP_DIR}/web"
pnpm install --frozen-lockfile
pnpm build

echo "==> Install + start systemd units"
sudo cp "${APP_DIR}/deploy/oracle/systemd/cpa-api.service" /etc/systemd/system/cpa-api.service
sudo cp "${APP_DIR}/deploy/oracle/systemd/cpa-web.service" /etc/systemd/system/cpa-web.service
sudo systemctl daemon-reload
sudo systemctl enable --now cpa-api
sudo systemctl enable --now cpa-web

echo "==> Install Nginx site"
sudo cp "${APP_DIR}/deploy/oracle/nginx/cpa.conf" /etc/nginx/sites-available/cpa.conf
sudo ln -sf /etc/nginx/sites-available/cpa.conf /etc/nginx/sites-enabled/cpa.conf
sudo rm -f /etc/nginx/sites-enabled/default
# Remember to set server_name to your real domain in the file above before reload.
sudo nginx -t
sudo systemctl reload nginx

echo
IP_GUESS="$(curl -s ifconfig.me || true)"
echo "==> bootstrap done. Remaining MANUAL steps (see deploy/oracle/README.md):"
echo "    No domain needed - use the free sslip.io host for your IP:"
echo "      HOST=${IP_GUESS:-<your-ip>}.sslip.io"
echo "    1. OCI console: add Security List ingress for tcp/80 and tcp/443"
echo "    2. VM firewall: open 80/443 in iptables and persist (README step 7)"
echo "    3. sudo sed -i \"s/YOUR_DOMAIN/\${HOST}/\" /etc/nginx/sites-available/cpa.conf && sudo systemctl reload nginx"
echo "    4. sudo certbot --nginx -d \"\${HOST}\"   (do AFTER opening port 80; README step 6)"
echo "    5. verify from your laptop:  curl https://\${HOST}/api/healthz"
