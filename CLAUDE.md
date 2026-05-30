# CLAUDE.md — codebase rules for the CPA AI Assistant

This file tells Claude how to work in this repo. Read it before changing
anything. The rules are derived from real bugs we already fixed — each
one is here because we got burned by NOT following it.

---

## 1. Repo layout (one-screen tour)

```
app/                         # FastAPI backend (Python 3.12)
  api/routes/                # Each router file mounts under a /prefix
    auth.py                  # /auth/register, /login, /refresh, /verify, /reset, /me, /me/locale
    engagements.py           # /engagements — filters type='comparisons' OUT of lists
    files.py                 # /engagements/{eid}/files — firm-scoped uploads
    comparisons.py           # /comparison/runs — USGAAP <> IFRS feature
    audit_routes.py          # /engagements/{eid}/audit — samples, JE tests, workpapers
    analyze.py, gl.py, coa.py, clients.py, tweaks.py, admin.py, health.py
    query.py, agent_route.py, knowledge.py, sources.py, ...
  api/auth.py                # current_principal + current_principal_permissive (both
                             #   fall back to the shared demo user — login was dropped)
  audit/workpapers/          # render_template + render_pdf_bytes + fonts/
  agent/                     # run_agent loop + Tool dataclass
  rag/                       # query_engine, chunker, vector_store, citation
  services/                  # Cross-cutting orchestrators (NOT routes, NOT models)
    comparison_orchestrator.py
    comparisons_engagement.py
  ingest_docs/extractors/    # pdf_text, docx, csv_, excel, excel_narrative
  db/models/                 # SQLAlchemy 2.0 declarative; one file per domain
  storage/                   # paths + s3 wrapper (memory backend for tests)
  llm/                       # Ollama Cloud client with KeyRotator + FakeLLM
  embeddings/                # HashEmbedder (default) + MultilingualE5
config/
  workpaper_templates/       # str.Template-based markdown templates
  standards_registry.yaml    # corpus sources
migrations/versions/         # Alembic — sequential 0001_, 0002_, 0003_
tests/unit/                  # Pytest, NO DB by default (use FakeLLM + MemoryStores)
web/                         # Next.js 15 frontend (App Router, RSC)
  src/app/(app)/             # Authenticated routes — layout reads cpa_locale cookie
  src/app/api/               # Route handlers (mostly dead — see §7 below)
  src/components/            # Server + client components by domain
  src/lib/                   # i18n, api/client, auth, utils
  next.config.mjs            # rewrites /api/:path* → ${INTERNAL_API_BASE}/:path*
  pyproject.toml             # core deps + [parse,agent,crawl,s3,ml,ocr,pdf] extras
render.yaml                  # Render Blueprint: cpa-api + cpa-web services
```

Quick mental model: backend = FastAPI + SQLAlchemy 2.0 (async, asyncpg) +
Postgres + Qdrant + Ollama Cloud; frontend = Next 15 RSC + a thin
server-only api client. **Auth.js is gone** — `web/src/lib/auth.ts` is a
stub and the api resolves every request to a shared demo user (see §3
Auth). Render free tier hosts both services; the web tier rewrites
`/api/*` straight to the api tier with no extras.

### Request lifecycle (end to end)
1. Browser hits `web` at `/api/<path>` (or `/api/stream/*` /
   `/api/comparison/*` for SSE). `next.config.mjs` `rewrites()` forwards
   `/api/*` to `${INTERNAL_API_BASE}/*` with **no** header manipulation;
   the `/api/stream` and `/api/comparison` Route Handlers are explicit
   proxies (they add cold-start retries / SSE passthrough).
2. `cpa-api` (`app/main.py::create_app`) runs the request through
   `BaseExceptionGuard` (catches `BaseException`-not-`Exception` panics →
   problem+json 500), CORS, then the matched router.
3. A route depends on `current_principal` → resolves the (demo) user, then
   calls `ensure_in_firm(eid, ...)` for engagement-scoped data (§5).
4. LLM work goes through `app/llm/client.py` (`OllamaCloudLLM` + KeyRotator,
   or `FakeLLM` when `CPA_LLM_BACKEND=fake`); RAG retrieval through
   `app/rag/query_engine.py` against Qdrant (or `MemoryVectorStore`).
5. Long work (comparison orchestrator, standards ingest) is fired as a
   tracked `asyncio.create_task`; the route returns immediately and the
   client polls status over SSE.

---

## 2. Workflow rules

### Before changing code
- Read the file you're editing AND its enclosing module — bugs hide in
  unchanged neighbour lines.
- `grep` for callers when you change a function's signature, return shape,
  or precondition.

### Before committing
- **Backend**: `.venv/bin/python -m ruff check . && .venv/bin/python -m pytest tests/unit -q`
- **Frontend**: `cd web && pnpm exec tsc --noEmit && pnpm exec eslint src tests`
- Both must be all-green. CI runs the same thing on push.

### After pushing
- Render does NOT auto-deploy on this branch — the user has to click
  "Deploy" manually for `cpa-api` and/or `cpa-web` in the Render
  dashboard. Tell the user explicitly which commit needs which service
  redeployed.
- Migrations run on `cpa-api` startup via the entrypoint
  (`python -m alembic upgrade head && exec python -m uvicorn ...`).
  If your change adds an Alembic file, the user needs to redeploy
  cpa-api before the new tables/columns exist.
- The bundled DejaVu Sans TTFs live in `app/audit/workpapers/fonts/`
  and are force-included in the wheel via `[tool.hatch.build.targets.wheel.force-include]`.
  Anything you put outside `app/` will NOT ship.

### Commit message style
Conventional Commits (`feat(...):`, `fix(...):`, `style(...):`,
`test(...):`). Subject line ≤ 72 chars. Body explains the WHY and the
failure scenario, not the WHAT — the diff already shows the what.

---

## 3. Backend rules

### Async + CPU-bound code
- **NEVER call CPU-bound code directly from an async handler.** PDF
  rendering with fpdf2 (~60-120 s for a multi-issue Hebrew memo) blocks
  the single Render worker past the edge timeout → 502.
  Always wrap in `asyncio.to_thread(...)` and cap with `asyncio.wait_for`.
- **NEVER await an LLM call without a timeout.** Use
  `asyncio.wait_for(llm.complete(...), timeout=120.0)`. Without it, a
  slow Ollama Cloud response pins runs in "detecting" forever.
- Background work (`asyncio.create_task`) MUST be kept in a strong-ref
  set so the GC can't reap it. See `_BACKGROUND_TASKS` in
  `app/api/routes/comparisons.py`.

### SQLAlchemy + enums
- **Python enum member NAMES must equal their VALUES** when the column
  uses `SAEnum`. SQLAlchemy serializes the member name; the Postgres
  enum type stores the value. Mismatched names cause
  `InvalidTextRepresentationError`. Example fix in commit `7ad67b4`:
  `Framework.us_gaap = "US"` was wrong → `Framework.US = "US"` works.
- `expire_on_commit=False` is set globally in `app/db/session.py`, so
  ORM objects survive `await session.commit()`. Don't expect SQLAlchemy
  to auto-refresh.
- The hidden `comparisons` engagement is excluded from `list_engagements`
  ONLY. Any new endpoint that iterates engagements per firm must add
  `.where(Engagement.type != EngagementType.comparisons)` — there's no
  global filter.

### Auth — READ THIS, the model changed
- **Login was removed** (commit `970e3ca` "drop login flow"). Today
  **every request resolves to the shared `demo@cpa.example` user.** Both
  resolvers in `app/api/auth.py` try a real JWT (Bearer) then an admin
  `X-API-Key`, then fall back to the demo user:
  - `current_principal` — falls back to demo; raises **503** only if the
    demo user hasn't been provisioned yet.
  - `current_principal_permissive` — identical fallback, raises **401**
    instead of 503 when the demo user is missing.
  The historical "strict vs permissive" split is now mostly cosmetic. The
  register/login/refresh/verify/reset endpoints still exist and still mint
  working JWTs, so a client that DOES send a Bearer resolves to its real
  user — but nothing in the shipped UI sends one.
- The demo user is provisioned at startup by `lifespan` →
  `app/services/demo_bootstrap.py::ensure_demo_user_exists` (idempotent;
  also created lazily on first request). It is treated as **admin**
  everywhere.
- The frontend mirrors this: `web/src/lib/auth.ts` is a **stub** — `auth()`
  returns a fake session with `accessToken: undefined`. So every browser
  proxy must forward **without requiring a token**. Gating a proxy on
  `session.accessToken` silently 401s the whole feature (this is exactly
  what killed Chat — see footgun table). Attach a Bearer only `if` one
  exists; never hard-fail on its absence.
- **Security reality:** this is single-shared-tenant demo mode — do NOT
  put real multi-tenant customer data through it. The firm-isolation
  plumbing is still intact and MUST be preserved (§5) so real auth can be
  restored later without reintroducing leaks.

### File uploads
- The `files` table requires a non-null `engagement_id`. The USGAAP <>
  IFRS feature works around this by creating a hidden per-user
  engagement (`type='comparisons'`) — see
  `app/services/comparisons_engagement.py`. Don't make `engagement_id`
  nullable.
- **Always size-check `UploadFile.size` BEFORE `await f.read()`** —
  reading large files into RAM before checking is a known OOM vector on
  the 512 MB free tier. Both upload paths now do this:
  `comparisons.create_run` (per-file `MAX_FILE_SIZE` + aggregate
  `MAX_TOTAL_UPLOAD`, `del body` between iterations) and
  `files.upload_file`. Keep the early `f.size` guard if you touch either.

### SSE responses
- Cloudflare buffers small SSE responses until enough bytes accumulate.
  Required for **every** SSE endpoint:
  1. 2 KB preamble of SSE comment lines (`: xxx...\n\n`) sent immediately.
  2. Heartbeat (`: heartbeat\n\n`) every 5 s.
  3. Headers: `Cache-Control: no-cache, no-transform`,
     `Content-Encoding: identity`, `X-Accel-Buffering: no`.
  See `stream_run` in `app/api/routes/comparisons.py` for the template.
  The three SSE endpoints are `comparison/runs/{id}/stream`,
  `engagements/{eid}/files/{id}/status/stream`, and `query/stream` — all
  follow the template. SSE consumers (`chat.tsx::parseSSE`,
  `RunStatusPill`) split on `\n\n` and ignore `:`-comment lines, so the
  preamble/heartbeat are invisible to them — never emit a bare `data:`
  frame as a keepalive.

### Optional dependencies
- Don't catch only `ImportError` when wrapping optional native libs.
  WeasyPrint raises `OSError` at import/run time when libpango/libcairo
  are missing. Catch `(ImportError, OSError)` and fall back. See
  `render_pdf_bytes` in `app/audit/workpapers/renderer.py`.
- If the lib is genuinely needed by core features, MOVE IT TO CORE DEPS
  in `pyproject.toml` instead of relying on `[parse]`/`[pdf]` extras.
  Render's blueprint sync ignored our `buildCommand` change three times
  in a row — extras are a deploy footgun. Examples now in core:
  `openpyxl`, `pdfplumber`, `python-docx`, `fpdf2`, `python-bidi`.

### LLM JSON parsing
- LLMs return JSON with leading/trailing prose, `NaN`/`Infinity`
  literals, and sometimes strings where numbers are expected. The
  `_parse_json` helpers in `comparison_orchestrator.py` and
  `agent/agent.py` strip markdown fences and recover from prose. Use
  them; don't `json.loads` raw model output.
- **`isinstance(True, int)` returns True in Python.** When validating
  numeric LLM output, use `type(x) in (int, float)` or check explicitly.

### LLM key rotation (`app/llm/`)
- `OllamaCloudLLM._request` drives a `KeyRotator` state machine (keys are
  `active` / `cooling` / `disabled`). Outcomes: **429** → cool the key +
  advance cursor; **401/403** → disable the key permanently; **5xx /
  network error** → retry the SAME key (the rotator does NOT advance on a
  plain server-error report) up to `ollama_max_retries_per_key`, then the
  client calls `rotator.cooldown_key()` to cool it and fan out to the next
  key. Without that fan-out a single bad key would burn the whole attempt
  budget — keep it (regression tests in `tests/unit/test_rotator.py`).
- `stream()` does NOT fail over mid-stream by design.
- Keys come from `OLLAMA_API_KEYS` (newline/comma separated) or
  `OLLAMA_API_KEYS_FILE`; `resolved_api_keys()` dedupes + strips. Tests and
  CI use `CPA_LLM_BACKEND=fake` (`FakeLLM`) so no keys are needed.

### PDF rendering (fpdf2)
- Register ALL FOUR font styles (`""`, `"B"`, `"I"`, `"BI"`) under the
  same family name. fpdf2 raises `Undefined font: uniI` if you call
  `set_font(style="I")` without registering it.
- Reset cursor to `pdf.l_margin` before every `multi_cell`. Without
  this, a previous-line residual can shrink available width and trigger
  "Not enough horizontal space".
- Apply `bidi.algorithm.get_display()` to Hebrew lines for logical →
  visual reordering, then render with `align="R"`.
- The chunked fallback in `_render_line`/`_render_md_line` must NEVER
  re-emit text that's already on the page. Each chunk gets its own try
  and an isolated ASCII substitution on failure.

### Tests
- **Python 3.12 is required** (`pyproject.toml` pins `>=3.12,<3.13`); a
  3.11 venv will fail to install the editable package. Create the venv
  with `python3.12 -m venv .venv` and install with the test extras:
  `.venv/bin/pip install -e ".[parse,agent,crawl,s3]"` plus
  `pytest pytest-asyncio ruff`.
- **157 unit tests** under `tests/unit/`. They DO NOT touch the database —
  use FakeLLM, MemoryVectorStore, MemoryObjectStore. Run them with the
  in-memory backends so nothing reaches out to Postgres/MinIO/Ollama:
  `CPA_LLM_BACKEND=fake CPA_S3_BACKEND=memory CPA_EMAIL_SINK=memory \
   .venv/bin/python -m pytest tests/unit -q`.
  If a new test needs DB, wire it in carefully or push the assertion to
  Playwright.
- Playwright lives in `web/tests/e2e/`. Run live against the deploy:
  `BASE_URL=https://cpa-web-01mj.onrender.com pnpm exec playwright test ... --project=chromium --workers=1`

---

## 4. Frontend rules

### Where to put visible strings
- **Every visible UI string goes in `web/src/lib/i18n/{en,he}.ts`.**
  Never hardcode user-facing text in JSX. Use `t("key", locale)` (server
  component) or `t("key", useLocale())` (client component).
- Missing Hebrew keys fall back to English — that's fine, but try to add
  the translation when you add the key.
- Placeholders use `{var}`: `t("usgaap.could_not_load", locale, { id: runId })`.

### Server vs client components
- `apiFetch()` from `web/src/lib/api/client.ts` is SERVER-ONLY. Calling it
  from a `"use client"` component fails silently. It reads the (now stub)
  session for a token — which is always `undefined` — so it effectively
  forwards unauthenticated; the api's demo-user fallback handles it.
- Client-side fetches MUST hit `/api/<path>` directly. Next's
  `rewrites()` in `next.config.mjs` forwards to the api with NO header
  manipulation (no bearer token, no path strip). The `/api/cpa/...`
  Route Handlers are **dead** (verified: nothing in `src/` calls them) —
  don't use them and don't add new code that does.
- The `cpa_locale` cookie is `SameSite=Lax`, client-readable. The
  root layout reads it via `cookies()` for SSR `dir`/`lang`; the
  `(app)/layout` reads it again for the client `LocaleProvider`.

### Error boundaries
- Every route that throws on api failure needs an `error.tsx` boundary
  OR an inline try/catch returning a styled error card. Letting Next's
  default 500 page show is a UX bug (the opaque "Application error:
  Digest: …" gives the user nothing).

### Component file naming
- PascalCase for components: `UploadDropzone.tsx`, not `upload-dropzone.tsx`.
- One default export per file when possible. Shared types live next to
  the component or in `web/src/lib/api/types.ts`.

---

## 5. Multi-tenancy + security

- Every engagement-scoped endpoint must call `ensure_in_firm(eid, principal, session)`
  from `app/api/routes/engagements.py` BEFORE returning data. This is
  the only firm-isolation check.
- The hidden `comparisons` engagement is per-USER, not per-firm. Two
  users in the same firm get separate engagements named
  `__comparisons__:<user_id>`. Don't change this — sharing it leaks
  one user's uploads to their firm-mates.
- The demo user (`demo@cpa.example`) is SHARED across all browsers and is
  now the principal for **every** route (login was dropped), not just
  `/comparison/*`. Everyone lands on the same admin principal. Don't put
  real customer data through it. `ensure_in_firm` still runs and still
  matters — it's what keeps the door shut if/when real auth returns.
- Never log raw uploaded file contents, JWTs, or user emails at INFO+.
  `app/logging_setup.py` enforces structured logging — use logger
  arguments (`logger.info("event", file_id=fid)`) not f-strings.

---

## 6. Deployment specifics (Render)

- Two services: `cpa-api` (Python) and `cpa-web` (Node). Both auto-build
  from the connected branch when the user clicks Deploy.
- `cpa-api` startup: `alembic upgrade head && uvicorn app.main:app`.
  Any new migration runs on the next boot.
- `cpa-web` startup: `pnpm start` (next standalone). Reads `INTERNAL_API_BASE`
  env var to forward `/api/*` to the api tier.
- `cpa-db` is a Render-managed Postgres. The `DATABASE_URL` env var on
  cpa-api uses `fromDatabase: name: cpa-db` so it's wired automatically.
  Migrations apply to it directly; no separate cpa-db deploy needed.
- Render's free tier spins down idle services after ~15 min. First
  request after idle can take 30-60 s to cold-start. Don't interpret
  cold-start latency as a bug.
- `render.yaml` is the source of truth for service config, BUT Render
  often ignores changes to it until the dashboard is manually resynced.
  When in doubt, change `pyproject.toml` core deps instead of
  `render.yaml` extras.

---

## 7. Known footguns (don't repeat these)

| What went wrong | Where to look | Fix landed in |
|---|---|---|
| `Framework.us_gaap = "US"` — enum name ≠ value → 500 on UPDATE | `app/db/models/comparison_models.py` | `7ad67b4` |
| Optional `[parse]` extras silently skipped by Render → "openpyxl not installed" | `pyproject.toml` core deps | `9abfc8c` |
| WeasyPrint `OSError` escapes `except ImportError` → opaque 500 | `app/audit/workpapers/renderer.py` | `cd7c154` |
| fpdf2 "Not enough horizontal space" → font missing or chunk overflow | same file | `dcb3708`, `b5f68d2` |
| fpdf2 "Undefined font: uniI" → italic style not registered | same file | `1cd1f50` |
| Cloudflare buffers SSE → pill stuck on initial status | `app/api/routes/comparisons.py::stream_run` | `6b7a5b7` |
| `current_principal` rejected demo user → "missing credentials" | `app/api/auth.py` | `40a8a09` |
| Frontend hit `/api/cpa/*` (dead) instead of `/api/*` rewrite | many components | `37f7180` |
| LLM corpus too big → Ollama 400 | `_build_corpus` in orchestrator | `3b1fd8f` |
| Background `asyncio.create_task` reaped by GC | comparisons.py `_BACKGROUND_TASKS` set | `f6cee93` (original) |
| Wheel didn't ship the bundled TTFs | `pyproject.toml force-include` | `b5f68d2` |
| Chat dead: `/api/stream` proxy 401'd on stub session's empty token | `web/src/app/api/stream/[...path]/route.ts` | audit fix |
| `files.upload_file` read body before size check → OOM vector | `app/api/routes/files.py` | audit fix |
| One Ollama key 5xx-ing starved all keys (no fan-out on server error) | `app/llm/client.py` + `ollama_rotator.py` | audit fix |
| Model-level `403` (no account access to a tag) disabled ALL keys → bogus "keys exhausted" | `app/config.py` model pin; verify tag entitlement (curl) before pinning | `qwen3.5:cloud` 403'd; fallback `gpt-oss:120b` |
| `files`/`query` SSE missing preamble+heartbeat → buffered by edge | `files.py`, `query.py` | audit fix |
| `query_engine` `top_k or` / `min_score or` discarded an explicit `0` | `app/rag/query_engine.py` | audit fix |
| `users.locale` server_default stuck at `en` while ORM default = `he` | migration `0006` | audit fix |
| `ALTER TYPE ADD VALUE` in a DO/txn block → fails on fresh deploy | migration `0002` (autocommit_block) | audit fix |
| Duplicate `_http_code` def silently shadowing the first | `app/api/errors.py` | audit fix |

---

## 8. When in doubt

- Run `git log --oneline -20` and look at recent commits — they document
  what was tried and what stuck.
- Read the closest existing example before inventing a pattern.
- If a fix touches more than 3 files, write down the design in chat
  before editing.
- Tests fail in CI but pass locally → check `ruff check .` from the
  repo root and re-run with `[parse,agent,crawl,s3]` extras installed.

---

## 9. Configuration & environment (`app/config.py`)

Settings are pydantic-settings, loaded from env / `.env`, `case_sensitive=
False`, unknown keys ignored. Defaults target the docker-compose stack.

**LLM model is pinned to `qwen3.5:397b-cloud`.** Every AI call — RAG
(`query_engine`), the comparison orchestrator, the agent loop, and Hebrew
translation — goes through the single `get_llm()` → `OllamaCloudLLM` client,
which reads `settings.ollama_model`. That default is hardcoded in
`app/config.py`, and the deployment configs (`render.yaml`,
`docker-compose.yml`, the Helm `api-secret.yaml`, `.env.example`) all set
`OLLAMA_MODEL=qwen3.5:397b-cloud` so nothing overrides it back. To change the
model, update ALL of those places together — changing only `app/config.py`
lets the deploy env win. `gpt-oss:120b` is the known-good fallback the keys
are entitled to.

**Before switching models, VERIFY the account is entitled to the new tag.**
We tried pinning `qwen3.5:cloud` and the whole AI surface went down: Ollama
Cloud returned `403 Forbidden` for that model (the plan/keys had no access).
A `403` makes the `KeyRotator` mark the key **DISABLED for the process
lifetime** (`report_unauthorized`), so a model-level 403 burned through BOTH
keys and surfaced as the misleading `AllKeysExhausted` → "All Ollama Cloud
API keys are exhausted." It was NOT a key/quota/round-robin problem — every
key hit the same entitlement wall. Confirm a tag works (`curl -sS
https://ollama.com/api/chat -H "Authorization: Bearer $KEY" -d
'{"model":"<tag>","messages":[{"role":"user","content":"hi"}],"stream":false}'`
→ expect 200, not 403) before pinning it. After a model-induced disable, the
keys stay dead until the process restarts (a redeploy resets rotator state).

| Group | Vars (defaults) | Notes |
|---|---|---|
| Ollama | `OLLAMA_API_KEYS` / `OLLAMA_API_KEYS_FILE`, `OLLAMA_MODEL` (`qwen3.5:397b-cloud`), `OLLAMA_BASE_URL` (`https://ollama.com`), `OLLAMA_MAX_RETRIES_PER_KEY` (2), `OLLAMA_REQUEST_TIMEOUT_SECONDS` (120), `OLLAMA_RATE_LIMIT_COOLDOWN_SECONDS` (60) | keys file wins over inline |
| Database | `DATABASE_URL` | `_ensure_asyncpg_dsn` rewrites `postgres://`/`postgresql://` → `postgresql+asyncpg://` and `sslmode=` → asyncpg `ssl=`. Don't hand-write the driver. |
| Qdrant | `QDRANT_URL`, `QDRANT_API_KEY` | |
| Object store | `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION` | `CPA_S3_BACKEND=memory` swaps in `MemoryObjectStore` |
| Embeddings | `EMBED_MODEL` (multilingual-e5-large), `EMBED_DEVICE` (cpu) | default embedder is the hash embedder unless ml extra + model present |
| Auth | `JWT_SECRET`, `JWT_ACCESS_TTL_SECONDS` (1800), `JWT_REFRESH_TTL_SECONDS` (30d), `ADMIN_API_KEY` | admin key → synthetic admin principal |
| SMTP | `SMTP_HOST/PORT/USERNAME/PASSWORD/FROM/STARTTLS` | `CPA_EMAIL_SINK=memory` collects mail in-process |
| Retrieval | `RETRIEVAL_TOP_K` (8), `RETRIEVAL_MIN_SCORE` (0.25), `RETRIEVAL_LANG_STRICT_HE` (true) | pass `0`/`0.0` explicitly to override — code uses `is None`, not `or` |
| Misc | `LOG_LEVEL`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `CPA_CORS_ORIGINS`, `CPA_LLM_BACKEND` (`ollama`/`fake`), `AUTH_URL` | |

Backend test trifecta: `CPA_LLM_BACKEND=fake CPA_S3_BACKEND=memory
CPA_EMAIL_SINK=memory`. `get_settings()` is `lru_cache`d — tests that
tweak env must clear it.

---

## 10. Backend subsystem map

- **Routers** (mounted in `app/main.py`): `health`, `auth`, `clients`,
  `engagements`, `files`, `query`, `sources`, `analyze`, `audit_routes`,
  `coa`, `gl`, `tweaks`, `admin`, `agent_route`, `knowledge`,
  `comparisons`. Each owns its `/prefix`.
- **DB models** (`app/db/models/`, one file per domain): `auth_models`
  (Firm/User/UserTweaks/AuthToken), `engagement` (Client/Engagement),
  `files`, `books` (ChartOfAccount/GLEntry/TrialBalance/CoaMapping), `bank`,
  `comparison_models`, `audit_models`, `standards_ingest`,
  `observability` (QueryLog/AgentRun/AuditLog). Migrations
  `0001`→`0006`, single linear head — verify with
  `python -c "from alembic.script import ScriptDirectory; ..."` or just
  keep `down_revision` chained.
- **RAG** (`app/rag/`): `query_engine` (retrieve → prompt → validate
  citations → refuse if top score `< min_score`), `chunker`,
  `vector_store` (Qdrant + `MemoryVectorStore`), `citation`,
  `knowledge_graph`, `lang` (he/en detection).
- **Comparison feature** (`app/services/comparison_orchestrator.py`):
  parse uploads → detect framework with calibrated confidence → identify
  issues → retrieve US GAAP + IFRS standards side-by-side → verifier pass.
  Hebrew memo prose is generated/pre-translated and cached on
  `ComparisonRun.translations_he`. Memo assembly + i18n live in
  `comparisons.py`; PDF render in `audit/workpapers/renderer.py`.
- **Audit** (`app/audit/`): `sampling`, `three_way_match`, JE tests
  (`benford`, `round_amounts`, `late_postings`, `weekend_holiday`,
  `unusual_user`, `threshold`), workpaper rendering.
- **Ingest**: `ingest_docs/extractors/` (pdf/docx/csv/xlsx → spans);
  `ingest_standards/` (discovery → robots → fetch → parse → pipeline,
  driven from `admin` route as a tracked background task).
- **Storage/LLM/email** are all behind factories with in-memory test
  doubles: `get_object_store`, `get_llm`, email memory sink. Reset
  helpers exist for tests (`reset_object_store`, `reset_llm`).
