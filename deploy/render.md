# Deploy to Render — zero CLI, click-through

What you'll have at the end: `https://cpa-web-XXXX.onrender.com` open in a
browser, sign-in working, every screen reachable, chat answers powered by
your Ollama Cloud keys.

**What "free" gets you here:**
- Cold start after 15 min idle (~30 s wake-up).
- 512 MB RAM per service — fine because we ship a slim image.
- Free Postgres on Render expires 90 days after creation. Renew or move
  to Neon (also free, no expiry) when this matters.
- File uploads are in-memory (`CPA_S3_BACKEND=memory`), so files are lost
  when a service restarts. Swap to Cloudflare R2 when you want
  persistence; see "Adding R2" at the end.

---

## 1) Prerequisites (~5 min, one-time)

### a) Qdrant Cloud free cluster
1. Sign up at <https://cloud.qdrant.io> (Google/GitHub login, no card).
2. Click **Create Cluster** → **Free Tier (1 GB)** → pick the region
   closest to Render Oregon (`us-east-1` works too).
3. After provisioning, open the cluster and copy:
   - **Cluster URL** — something like `https://xxxx.eu-central-1.aws.cloud.qdrant.io`
   - **API key** (create one under **Data Access Control** → **API keys**)

### b) Your Ollama Cloud keys
Have your existing `OLLAMA_API_KEYS` ready as a newline- or
comma-separated string. The KeyRotator we built round-robins them and
honors per-key cooldowns automatically.

### c) Render account
Sign up at <https://render.com>. GitHub login is easiest because the
Blueprint flow needs repo access.

---

## 2) Deploy the Blueprint (~3 min)

1. In Render, click **New** → **Blueprint**.
2. **Connect** your GitHub account and pick the **CPA** repo, branch
   `claude/cpa-gaap-ifrs-system-3Dphm` (or main once PR #1 lands).
3. Render reads `render.yaml` and shows three resources:
   - `cpa-api`  (Web service)
   - `cpa-web`  (Web service)
   - `cpa-db`   (Postgres database)
4. Render asks for the **sync: false** secrets. Paste:
   - `OLLAMA_API_KEYS` — your keys (newline-separated is fine).
   - `QDRANT_URL` — the cluster URL from Qdrant Cloud (full https://…).
   - `QDRANT_API_KEY` — the Qdrant API key.
   - Leave `AUTH_URL` and `INTERNAL_API_BASE` **blank for now** — we'll
     fill them after the first deploy when we know the assigned URLs.
5. Click **Apply**. Render starts building both images.

The first build takes ~6–10 min. You can watch logs from each service.

---

## 3) Connect the two services (~2 min, one-time)

After the first build, you'll have two URLs in Render:
- `cpa-api` → e.g. `https://cpa-api-abcd.onrender.com`
- `cpa-web` → e.g. `https://cpa-web-efgh.onrender.com`

Now back-fill the two pending env vars:

### `cpa-web` service → **Environment**
- `INTERNAL_API_BASE` = `https://cpa-api-abcd.onrender.com` (the cpa-api URL)
- `AUTH_URL` = `https://cpa-web-efgh.onrender.com` (this service's own URL)

Click **Save Changes** — Render auto-redeploys.

---

## 4) Smoke-test (~1 min)

Open `https://cpa-web-efgh.onrender.com` in a browser:

1. You should land on `/login` (no session yet).
2. Click **Create one** → register with any email + ≥12-char password +
   firm name. You'll be auto-signed-in and bounced to `/engagements`.
3. Create your first engagement (Client name, Engagement name, type).
4. From the dashboard, click into **Chat** and ask something. The
   answer will refuse-with-citation-discipline if Qdrant is still empty;
   it will return a cited answer after step 5.

### Confirm the LLM is actually wired
Hit `https://cpa-api-abcd.onrender.com/admin/rotator` with
`X-API-Key: <ADMIN_API_KEY>` (auto-generated; copy from Render
Environment) — you'll see your rotator slots with masked keys.

---

## 5) Optional — feed the corpus

The chat is most useful with real standards. Trigger the crawl via the
Render **Shell** tab on `cpa-api`:

```bash
python -m app.ingest_standards.jobs.run_ingest --source fasb_asc_public
python -m app.ingest_standards.jobs.run_ingest --source pcaob_as
python -m app.ingest_standards.jobs.run_ingest --source us_irc_cornell
```

Each run discovers a polite (~20-30) URL slice, fetches with ETag caching
into Qdrant. ASC and IFRS full texts are paywalled — only public
excerpts get pulled.

---

## 6) When you outgrow free

Three small upgrades, each independently:

### Persistent file storage (Cloudflare R2 free 10 GB)
Sign up at <https://dash.cloudflare.com>, create an R2 bucket, generate
an API token, then on `cpa-api` set:
```
CPA_S3_BACKEND=s3
S3_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com
S3_ACCESS_KEY=<r2 access key>
S3_SECRET_KEY=<r2 secret>
S3_BUCKET=cpa
S3_REGION=auto
```

### Postgres that doesn't expire (Neon free)
Sign up at <https://neon.tech>, create a project, copy the
`postgresql://…` connection string into `DATABASE_URL` on `cpa-api`.
The config validator rewrites it to the `+asyncpg` form automatically.

### Keep services always-on
Bump either service to Render **Starter** ($7/mo) to remove the 15-min
idle sleep + give it 512 MB → 2 GB headroom.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `503 AllKeysExhausted` from `/query` | Your Ollama keys are all rate-limited at once. Check `/admin/rotator` for cooldown timers; add more keys to `OLLAMA_API_KEYS`. |
| Web shows `/login` redirect loop | `AUTH_URL` doesn't match the browser host. Set it to **exactly** the URL you're visiting (`https://cpa-web-XXXX.onrender.com`, no trailing slash). |
| `Invalid token` on every request | The api was redeployed and re-generated `JWT_SECRET`. Sign out + sign in again. To pin: in `cpa-api` env, change `JWT_SECRET` from auto-generate to a manual value. |
| Chat hangs and times out | `INTERNAL_API_BASE` on the web service is wrong (typo / missing https://). Check Render env vars on `cpa-web`. |
| Qdrant errors at startup | Cluster paused (free tier suspends after long inactivity); reopen Qdrant Cloud to wake it. |
| `/healthz` returns 200 but `/readyz` is 503 | Expected — readiness fails when `OLLAMA_API_KEYS` is empty. Paste your keys in `cpa-api` env. |
