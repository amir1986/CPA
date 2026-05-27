# CLAUDE.md — codebase rules for the CPA AI Assistant

This file tells Claude how to work in this repo. Read it before changing
anything. The rules are derived from real bugs we already fixed — each
one is here because we got burned by NOT following it.

---

## 1. Repo layout (one-screen tour)

```
app/                         # FastAPI backend (Python 3.12)
  api/routes/                # Each router file mounts under a /prefix
    auth.py                  # /auth/register, /login, /me, /me/locale
    engagements.py           # /engagements — filters type='comparisons' OUT of lists
    files.py                 # /engagements/{eid}/files — firm-scoped uploads
    comparisons.py           # /comparison/runs — USGAAP <> IFRS feature
    audit_routes.py          # /engagements/{eid}/audit — samples, JE tests, workpapers
    query.py, agent_route.py, knowledge.py, sources.py, ...
  auth.py                    # current_principal + current_principal_permissive
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

Quick mental model: backend = FastAPI + SQLAlchemy + Postgres + Qdrant +
Ollama Cloud; frontend = Next 15 RSC + Auth.js + a thin server-only api
client. Render free tier hosts both services; the web tier rewrites
`/api/*` straight to the api tier with no extras.

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

### Auth
- `current_principal` is the strict default — requires a real
  Authorization header or X-API-Key.
- `current_principal_permissive` (in `app/api/auth.py`) falls back to
  the shared `demo@cpa.example` account when no creds are present.
  **Use this ONLY for browser-fetched routes that go through the bare
  `/api/*` rewrite in `web/next.config.mjs`** (which strips the bearer
  token). Currently only the `/comparison/*` routes use it. Adding it
  elsewhere creates a multi-tenant data leak — the demo user is shared
  across every browser.

### File uploads
- The `files` table requires a non-null `engagement_id`. The USGAAP <>
  IFRS feature works around this by creating a hidden per-user
  engagement (`type='comparisons'`) — see
  `app/services/comparisons_engagement.py`. Don't make `engagement_id`
  nullable.
- **Always size-check before `await f.read()`** — reading 50 MB into RAM
  for each of 10 files is a known OOM vector on the 512 MB free tier.
  Current code is vulnerable; if you touch it, fix it.

### SSE responses
- Cloudflare buffers small SSE responses until enough bytes accumulate.
  Required for every SSE endpoint:
  1. 2 KB preamble of SSE comment lines (`: xxx...\n\n`) sent immediately.
  2. Heartbeat (`: heartbeat\n\n`) every 5 s.
  3. Headers: `Cache-Control: no-cache, no-transform`,
     `Content-Encoding: identity`, `X-Accel-Buffering: no`.
  See `stream_run` in `app/api/routes/comparisons.py` for the template.

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
- 103 unit tests under `tests/unit/`. They DO NOT touch the database —
  use FakeLLM, MemoryVectorStore, MemoryObjectStore. If a new test
  needs DB, wire it in carefully or push the assertion to Playwright.
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
- `apiFetch()` from `web/src/lib/api/client.ts` is SERVER-ONLY (reads
  the Auth.js session). Calling it from a client component fails silently.
- Client-side fetches MUST hit `/api/<path>` directly. Next's
  `rewrites()` in `next.config.mjs` forwards to the api with NO header
  manipulation (no bearer token, no path strip). The `/api/cpa/...`
  pattern in the old codebase is dead — don't use it.
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
- The demo user (`demo@cpa.example`) is SHARED across all browsers
  hitting the unauthenticated `/comparison/*` routes. Anyone using the
  Skip flow lands on the same principal. Don't put real customer data
  through demo flows.
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

---

## 8. When in doubt

- Run `git log --oneline -20` and look at recent commits — they document
  what was tried and what stuck.
- Read the closest existing example before inventing a pattern.
- If a fix touches more than 3 files, write down the design in chat
  before editing.
- Tests fail in CI but pass locally → check `ruff check .` from the
  repo root and re-run with `[parse,agent,crawl,s3]` extras installed.
