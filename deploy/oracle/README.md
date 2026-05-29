# Migrating CPA from Render to an Oracle Cloud Always Free ARM VM

This is the operational runbook for moving the CPA app off Render's free tier
(which sleeps after 15 min and cold-starts in 30-60 s) onto an always-on OCI
Ampere A1 (ARM64) Ubuntu VM.

**This is a VM migration, not a framework migration. No application code
changes - only process management, env vars, networking, and TLS.** Everything
here lives under `deploy/oracle/` plus one optional GitHub Actions workflow.

---

## 0. What was discovered from the codebase (the stack you're moving)

The repo is **two services plus a database**, exactly as `render.yaml` runs them:

| Component | Stack (discovered) | Build | Start | Port |
|---|---|---|---|---|
| `cpa-api` | Python 3.12 (`pyproject.toml` pins `>=3.12,<3.13`), FastAPI + uvicorn, SQLAlchemy 2 async + asyncpg, Alembic | `pip install .` | `alembic upgrade head && uvicorn app.main:app` | `$PORT` on Render; **127.0.0.1:8000** here |
| `cpa-web` | Node >=22, Next.js 15 (App Router), pnpm >=9, `rootDir: web` | `pnpm install --frozen-lockfile && pnpm build` | `pnpm start` (`next start`) | **127.0.0.1:3000** |
| `cpa-db` | Render-managed Postgres 16 | - | - | 5432 |

- Health: api `/healthz` (liveness), `/readyz` (checks Ollama keys); web `/api/health`.
- The web tier proxies `/api/*` to the api via `next.config.mjs` `rewrites()` ->
  `INTERNAL_API_BASE`, with no header manipulation. We keep that model: Nginx is
  the only public listener and talks to the web tier; the api stays private on
  loopback and the web tier forwards `/api/*` to it.
- **External, no migration needed:** Qdrant Cloud, Ollama Cloud, SMTP. S3 uses the
  in-memory backend (`CPA_S3_BACKEND=memory`).
- **The catch:** the Postgres DB is Render-managed, so it leaves with Render. Per
  the decision taken, `DATABASE_URL` now points at an **external managed Postgres
  (Neon/Supabase)**. The app already normalizes `postgres://` and `sslmode=`
  DSNs (`app/config.py::_ensure_asyncpg_dsn`), so the provider's URL pastes in as-is.

### Required env var keys (full set)

Built from `app/config.py`, every `os.environ`/`process.env` reference, and
`render.yaml`. Fill the actual values into the two env files (step 4). Templates:
`deploy/oracle/env/cpa-api.env.example` and `cpa-web.env.example`.

- **cpa-api:** `DATABASE_URL`, `OLLAMA_API_KEYS` (or `OLLAMA_API_KEYS_FILE`),
  `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_RATE_LIMIT_COOLDOWN_SECONDS`,
  `OLLAMA_MAX_RETRIES_PER_KEY`, `OLLAMA_REQUEST_TIMEOUT_SECONDS`, `QDRANT_URL`,
  `QDRANT_API_KEY`, `CPA_VECTOR_BACKEND`, `JWT_SECRET`, `ADMIN_API_KEY`,
  `JWT_ACCESS_TTL_SECONDS`, `JWT_REFRESH_TTL_SECONDS`, `CPA_LLM_BACKEND`,
  `CPA_AGENT_BACKEND`, `CPA_EMBED_BACKEND`, `CPA_S3_BACKEND`, `CPA_EMAIL_SINK`,
  `LOG_LEVEL`, `AUTH_URL`, `CPA_CORS_ORIGINS`. Optional: `S3_*`, `SMTP_*`,
  `EMBED_MODEL`, `EMBED_DEVICE`, `RETRIEVAL_*`, `OTEL_EXPORTER_OTLP_ENDPOINT`.
- **cpa-web:** `INTERNAL_API_BASE`, `AUTH_SECRET`, `AUTH_URL`, `AUTH_TRUST_HOST`,
  `NEXT_PUBLIC_API_BASE`, `NEXT_PUBLIC_DEFAULT_LOCALE`, `NODE_ENV`,
  `NEXT_TELEMETRY_DISABLED`.

> ARM note: all api deps ship aarch64 wheels (asyncpg, pydantic-core, pdfplumber,
> pillow, ...), so no source builds are needed. The A1 VM has far more RAM than
> Render's 512 MB, so the old memory caps are no longer load-bearing.

---

## 1. Provision and access the VM

Assuming the Always Free Ampere A1 Ubuntu instance already exists:

```bash
ssh ubuntu@<VM_PUBLIC_IP>
sudo apt update && sudo apt upgrade -y
```

---

## Fast path (scripted)

Steps 2, 3, 5, 6-partial are automated. After you SSH in:

```bash
# get the templates onto the box first
git clone --branch claude/cpa-api-oracle-migration-BqigD \
  https://github.com/amir1986/CPA.git /home/ubuntu/cpa

# create + fill the env files (step 4) BEFORE running bootstrap
cp /home/ubuntu/cpa/deploy/oracle/env/cpa-api.env.example /home/ubuntu/cpa/.env
cp /home/ubuntu/cpa/deploy/oracle/env/cpa-web.env.example /home/ubuntu/cpa/web/.env
nano /home/ubuntu/cpa/.env          # fill REPLACE_ME, set https://<your-ip>.sslip.io
nano /home/ubuntu/cpa/web/.env
chmod 600 /home/ubuntu/cpa/.env /home/ubuntu/cpa/web/.env

# run it (sets up runtimes, deps, build, systemd units, Nginx on HTTP)
bash /home/ubuntu/cpa/deploy/oracle/scripts/bootstrap.sh
```

Then do step 7 (the two firewall layers - needs the OCI console) and step 6
(point Nginx at `<your-ip>.sslip.io` and run certbot for HTTPS). Do firewall
BEFORE certbot. The rest of this doc explains each step.

---

## 2. Install the runtime

`bootstrap.sh` does this; manual equivalent:

```bash
sudo apt-get install -y git curl ca-certificates build-essential nginx \
  software-properties-common netfilter-persistent iptables-persistent

# Python 3.12 exactly (deadsnakes => works regardless of Ubuntu release;
# 24.10/25.04 ship 3.13 which pyproject forbids)
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3.12-dev
python3.12 --version    # expect 3.12.x

# Node 22 (arm64) + pnpm
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
node -v                 # expect v22.x
sudo corepack enable
sudo corepack prepare pnpm@10.33.0 --activate
pnpm -v
```

---

## 3. Deploy the code

```bash
# already cloned in the fast path; otherwise:
git clone --branch claude/cpa-api-oracle-migration-BqigD \
  https://github.com/amir1986/CPA.git /home/ubuntu/cpa
cd /home/ubuntu/cpa

# api deps - editable install so 'git pull' updates code without reinstalling.
# Core deps only (matches Render's `pip install .`); add extras like ".[parse]"
# only if you enable those features.
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .

# web deps + build (do NOT start anything yet - env must exist first)
cd web && pnpm install --frozen-lockfile && pnpm build
```

---

## 4. Environment variables (CRITICAL - do not skip verification)

These never lived in git (they're in the Render dashboard), so recreate them:

```bash
cp /home/ubuntu/cpa/deploy/oracle/env/cpa-api.env.example /home/ubuntu/cpa/.env
cp /home/ubuntu/cpa/deploy/oracle/env/cpa-web.env.example /home/ubuntu/cpa/web/.env
nano /home/ubuntu/cpa/.env          # fill every REPLACE_ME
nano /home/ubuntu/cpa/web/.env
chmod 600 /home/ubuntu/cpa/.env /home/ubuntu/cpa/web/.env
```

Pull the actual values from the Render dashboard (cpa-api and cpa-web -> Environment).
Generate fresh secrets where it makes sense: `openssl rand -base64 32` for
`JWT_SECRET`, `ADMIN_API_KEY`, `AUTH_SECRET`. Set `DATABASE_URL` to your Neon/
Supabase URL. Set `AUTH_URL` and `CPA_CORS_ORIGINS` to `https://<your-ip>.sslip.io`
(see step 6 - you have no domain, so we use the free sslip.io host for your IP).

For several Ollama keys, leave `OLLAMA_API_KEYS` empty and use a key file
(systemd `EnvironmentFile` cannot hold multi-line values):

```bash
printf '%s\n' 'sk-key-one' 'sk-key-two' > /home/ubuntu/cpa/ollama_keys.txt
chmod 600 /home/ubuntu/cpa/ollama_keys.txt   # OLLAMA_API_KEYS_FILE points here
```

Confirm `.env` is gitignored and was never committed (it is - root `.gitignore`
line 33 `.env` and `web/.gitignore`):

```bash
cd /home/ubuntu/cpa
git check-ignore .env web/.env        # prints both paths => ignored
git log --all --oneline -- .env web/.env   # prints nothing => never committed
```

**Verify every required key is actually set** before declaring success:

```bash
set -a; . /home/ubuntu/cpa/.env; set +a
for k in DATABASE_URL QDRANT_URL QDRANT_API_KEY JWT_SECRET ADMIN_API_KEY \
         CPA_VECTOR_BACKEND CPA_LLM_BACKEND CPA_AGENT_BACKEND CPA_EMBED_BACKEND \
         CPA_S3_BACKEND CPA_EMAIL_SINK AUTH_URL CPA_CORS_ORIGINS; do
  if [ -z "${!k:-}" ]; then echo "MISSING: $k"; else echo "ok: $k"; fi
done
# Ollama: at least one of the two must be set
[ -n "${OLLAMA_API_KEYS:-}" ] || [ -s "${OLLAMA_API_KEYS_FILE:-/nonexistent}" ] \
  && echo "ok: ollama keys" || echo "MISSING: ollama keys"
```

> Back these values up in a password manager. If the VM is destroyed, the
> secrets are gone - the repo does not and must not contain them.

---

## 5. Process manager (replaces Render's managed process)

Two `systemd` units (sources in `deploy/oracle/systemd/`):

- `cpa-api.service`: `Restart=always`, `EnvironmentFile=/home/ubuntu/cpa/.env`,
  `ExecStartPre` runs `alembic upgrade head` (same order as Render), then uvicorn
  on `127.0.0.1:8000`.
- `cpa-web.service`: `Restart=always`, `EnvironmentFile=/home/ubuntu/cpa/web/.env`,
  runs `next start` on `127.0.0.1:3000`.

Install and enable on boot:

```bash
sudo cp /home/ubuntu/cpa/deploy/oracle/systemd/cpa-api.service /etc/systemd/system/
sudo cp /home/ubuntu/cpa/deploy/oracle/systemd/cpa-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cpa-api cpa-web
sudo systemctl status cpa-api cpa-web --no-pager
journalctl -u cpa-api -n 50 --no-pager     # confirm migrations ran + uvicorn up
```

---

## 6. Reverse proxy + HTTPS (replaces Render's automatic SSL)

**You don't have a domain, and Oracle does not give you a public one.** An OCI
instance only gets a public **IP** plus a *private* internal hostname
(`...oraclevcn.com`) that is not reachable from the internet. Let's Encrypt will
not issue a normal cert for a bare IP, so we use **sslip.io**: a free, no-signup
wildcard DNS where `<your-ip>.sslip.io` automatically resolves to your IP. That
gives Certbot a real hostname and you get genuine green-padlock HTTPS.

Pick your hostname from the VM's public IP (no DNS setup needed - sslip.io just
works). If your IP is `203.0.113.5`, your host is `203.0.113.5.sslip.io`:

```bash
# capture the host once so the commands below are copy-paste
IP=$(curl -s ifconfig.me)            # or read it from the OCI console
HOST="${IP}.sslip.io"
echo "public host = ${HOST}"
dig +short "${HOST}"                  # should print your IP (proves resolution)

# point Nginx server_name at it
sudo sed -i "s/YOUR_DOMAIN/${HOST}/" /etc/nginx/sites-available/cpa.conf
sudo nginx -t && sudo systemctl reload nginx

# Let's Encrypt via certbot (edits the Nginx file to add 443 + http->https redirect)
sudo snap install --classic certbot
sudo ln -sf /snap/bin/certbot /usr/bin/certbot
sudo certbot --nginx -d "${HOST}" --redirect -m you@example.com --agree-tos

# auto-renew is installed by the certbot snap; confirm:
sudo certbot renew --dry-run
```

> Certbot's HTTP-01 challenge needs port 80 reachable from the internet, so do
> **step 7 (open 80/443 in both firewall layers) BEFORE running certbot**, or the
> challenge times out.

> sslip.io and nip.io are on the Public Suffix List, so each `<ip>.sslip.io` is a
> separate registrable name for Let's Encrypt rate-limiting - issuance works fine.
> If a network you're on blocks sslip.io, a free `*.duckdns.org` subdomain (quick
> signup + token, A record set to your IP) works the same way with certbot.

Set `AUTH_URL` and `CPA_CORS_ORIGINS` in `/home/ubuntu/cpa/.env` and `AUTH_URL`
in `/home/ubuntu/cpa/web/.env` to `https://<your-ip>.sslip.io` to match. (If you
edit `web/.env` after the first build, rebuild web - see step 9 / footgun 3.)

The Nginx config (`deploy/oracle/nginx/cpa.conf`) proxies everything to the web
tier on 3000 and **disables `proxy_buffering`** so SSE (comparison runs, file
status, query stream) is not buffered at the edge - this matches the app's own
SSE preamble/heartbeat handling.

If you'd rather skip TLS entirely (private demo only): leave the HTTP-only config
on port 80, set the env URLs to `http://<your-ip>`, and skip certbot. Browsers
will mark it "Not secure".

---

## 7. Networking - the two-layer firewall (COMMON FAILURE POINT)

On Oracle, opening a port inside Ubuntu is not enough. **Both** layers must allow
80 and 443. If `curl localhost` works on the VM but external `curl` hangs, this is
almost always the cause. (api 8000 and web 3000 stay closed - they're loopback-only.)

### Layer 1 - OCI Security List / NSG (web console)

Networking -> Virtual Cloud Networks -> your VCN -> Subnet -> Security List ->
**Add Ingress Rules** (leave the existing tcp/22 rule in place):

| Stateless | Source CIDR | IP Proto | Dest port |
|---|---|---|---|
| No | 0.0.0.0/0 | TCP | 80 |
| No | 0.0.0.0/0 | TCP | 443 |

### Layer 2 - VM firewall (iptables, persisted)

Oracle Ubuntu images ship a restrictive iptables ruleset with a `REJECT` near the
end of `INPUT`. Insert ACCEPT rules **before** that REJECT, then persist:

```bash
sudo iptables -L INPUT --line-numbers          # find the REJECT line number (often ~6)
sudo iptables -I INPUT 6 -p tcp --dport 80  -m conntrack --ctstate NEW -j ACCEPT
sudo iptables -I INPUT 6 -p tcp --dport 443 -m conntrack --ctstate NEW -j ACCEPT
sudo netfilter-persistent save                 # writes /etc/iptables/rules.v4
sudo iptables -L INPUT --line-numbers          # verify ACCEPT sits above REJECT
```

> Do not `ufw enable` on top of this - mixing ufw with Oracle's existing iptables
> rules silently drops traffic. Use the iptables commands above. If you insist on
> ufw, flush the Oracle rules first (advanced; not covered here).

### Verify both layers

```bash
# from the VM (proves the app is up regardless of firewall):
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:3000/api/health
# from your LAPTOP (proves both firewall layers are open):
curl -s http://<your-ip>.sslip.io/api/healthz     # before certbot; https after
```

---

## 8. Verify the migration

Run from your **laptop**, not the VM (replace with your `<ip>.sslip.io` host):

```bash
HOST=203.0.113.5.sslip.io                      # your VM IP + .sslip.io
curl -s https://$HOST/api/healthz   # {"status":"ok"}  (api liveness via web rewrite)
curl -s https://$HOST/api/readyz    # {"ready":true,...} once Ollama keys are set
curl -s https://$HOST/api/health    # web tier health
curl -sI https://$HOST/             # web homepage, 200, valid TLS
```

Confirm these match what Render returned. Then prove it survives a reboot and that
every env-dependent feature works:

```bash
sudo reboot
# wait ~30s, then from your laptop re-run the curls above - both units are
# WantedBy=multi-user.target so they auto-start.

# env-dependent checks on the VM:
journalctl -u cpa-api -n 80 --no-pager        # DB connect + migrations clean (no asyncpg errors)
curl -s https://$HOST/api/readyz              # Ollama keys loaded
# exercise a real DB + Qdrant path through the UI (e.g. an engagement list / a query).
```

---

## 9. Ongoing deployment workflow

Manual update (on the VM):

```bash
cd /home/ubuntu/cpa
bash deploy/oracle/scripts/deploy.sh
# = git pull --ff-only -> pip install -e . --upgrade -> restart cpa-api
#   (migrations run via ExecStartPre) -> pnpm install + build -> restart cpa-web
```

Optional CI deploy on push: `.github/workflows/deploy-oracle.yml` SSHes in and runs
`deploy.sh`. It is inert until you add repo secrets `OCI_SSH_HOST`, `OCI_SSH_USER`,
`OCI_SSH_KEY` (private key), and optionally `OCI_SSH_PORT`. GitHub's runners must be
able to reach the VM's SSH port - if you restricted tcp/22 to your own IP in the OCI
Security List, widen it for the runners or keep deploying manually.

---

## Things most likely to bite you

1. **Firewall double layer (step 7).** External `curl` hangs but `curl localhost`
   works -> the OCI Security List or the iptables REJECT is still blocking.
2. **Env var completeness (step 4).** A missing `DATABASE_URL`/`QDRANT_*`/Ollama
   key fails silently (empty corpus, refusals, 503 on `/readyz`). Run the verify loop.
3. **`NEXT_PUBLIC_*` are build-time.** Change them -> rebuild web, a restart alone
   won't pick them up.
4. **systemd `EnvironmentFile` is not a shell.** No quotes, no `$VAR`, no multi-line
   - use `OLLAMA_API_KEYS_FILE` for multiple keys; URL-encode odd chars in `DATABASE_URL`.
5. **Python must be 3.12** (not 3.13) - the deadsnakes pin handles it.
