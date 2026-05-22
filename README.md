# CPA AI Assistant

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/amir1986/CPA/tree/claude/cpa-gaap-ifrs-system-3Dphm)

A green-field, comprehensive AI-powered CPA workbench — a full web product, not just a Q&A bot.

It (1) knows the standards with strict citations (US GAAP, IFRS, Israeli GAAP, AICPA / PCAOB / IAASB / Israeli audit, IL tax, US tax), (2) does the daily bookkeeping job (ingests TBs, GLs, bank statements, invoices, financial statements — xlsx / csv / pdf, OCR-aware), (3) analyzes (ratios, trends, common-size, anomalies), (4) tests and audits (sampling, JE tests, three-way match, cutoff, analytical procedures), (5) produces work product (workpapers, memos, management letters), (6) is orchestrable (every capability is a deterministic REST endpoint, with a higher-level `/agent` endpoint that chains them via LlamaIndex tool calling), and (7) is usable by humans (a polished bilingual EN+HE RTL-aware web app).

## Architecture

```
                 ┌──────────────── Browser ────────────────┐
                 │  Next.js client: chat (SSE), dashboards │
                 │  documents UI, compare, traces, admin   │
                 └────────────────────┬────────────────────┘
                                      │ HTTPS (cookie session)
                 ┌────────────────────┴────────────────────┐
                 │   Ingress (single host)                 │
                 │   /        → web Service                │
                 │   /api/*   → api Service                │
                 └─────────┬───────────────────┬───────────┘
                           │                   │
                 ┌─────────┴────────┐   ┌──────┴─────────────┐
                 │ Next.js (Node)   │   │ FastAPI            │
                 │ Auth.js + RSC    │──►│ deterministic +    │
                 │ TanStack Query   │◄──│ LlamaIndex agent   │
                 └──────────────────┘   └──┬───────────┬─────┘
                                           │           │
                       ┌───────────────────┘           └────────────────────┐
                       ▼                                                    ▼
              ┌──────────────┐  ┌────────────────┐  ┌──────────────────┐
              │ Postgres     │  │ Qdrant         │  │ Ollama Cloud LLM │
              │ (engagement  │  │ - cpa_knowledge│  │ + KeyRotator     │
              │  + auth)     │  │ - engagement   │  │ (circular)       │
              └──────────────┘  │   _docs        │  └──────────────────┘
                                └────────────────┘
              ┌────────────────┐  ┌────────────────┐
              │ S3 / MinIO     │  │ Multilingual   │
              │ (uploads + WP) │  │ E5 embeddings  │
              └────────────────┘  └────────────────┘
```

## Tech stack

| Layer | What we use |
| --- | --- |
| **Backend** | Python 3.12, FastAPI, SQLAlchemy 2 (async) + Alembic, Postgres 16, Qdrant (hybrid dense + BM25), LlamaIndex (RAG + FunctionAgent), Ollama Cloud LLM with circular `KeyRotator`, `intfloat/multilingual-e5-large` embeddings (CPU, in-process), aioboto3 → S3/MinIO, pdfplumber / pytesseract (EN+HE) / camelot / openpyxl + pandas for extraction, WeasyPrint for workpaper PDFs, slowapi rate limits, structlog + OpenTelemetry + Prometheus |
| **Frontend** | Next.js 15 (App Router, RSC, standalone Node), React 19, TypeScript 5, Tailwind 4 + shadcn/ui, Auth.js (Credentials), TanStack Query, Tremor + Recharts, Cytoscape.js (knowledge graph), `react-pdf` + `tus-js-client` (document analyzer), next-intl (EN/HE) + next-themes, Zustand (narrow local UI), nuqs (URL state), Shiki (code highlight), cmdk (command palette) |
| **Auth & sessions** | Auth.js cookie session bridging to a FastAPI-issued JWT (HS256, sliding TTL + refresh), bcrypt password hashing, email verify/reset via aiosmtplib (MailHog in dev) |
| **Build & tooling** | pnpm (web), uv (api), Make (single entrypoint), pre-commit, ESLint + Prettier, Ruff + mypy, vitest + React Testing Library, Playwright + `@axe-core/playwright`, schemathesis, testcontainers, openapi-typescript for type generation |
| **Ops** | Docker Compose (api + web + Caddy + postgres + qdrant + minio + mailhog) for local dev; single Helm chart with two Deployments (api + web) behind one Ingress; ServiceMonitor + HPA + NetworkPolicy; kind for smoke installs; cloud-agnostic (EKS/GKE/AKS) |

## Prerequisites

- Docker Desktop (or Colima/OrbStack) + Docker Compose v2
- `make`
- For host-side dev only: `python 3.12` + [`uv`](https://docs.astral.sh/uv/), `node 22` + `pnpm`
- 16 GB RAM recommended (E5 model + Qdrant + Postgres + Next dev server)

## Quick start — everything in Docker

```bash
git clone <repo> && cd CPA
cp .env.example .env                  # then paste OLLAMA_API_KEYS
make up                               # docker compose up -d --build
make seed                             # migrate + ingest fixture standards + seed firm/user
open http://localhost:8080            # Caddy: web on / and api on /api
```

Seeded login: printed by `make seed` (default `dev@cpa.local` / `devpassword`).

| Service | URL |
| --- | --- |
| App (web + api via Caddy) | http://localhost:8080 |
| MailHog (dev SMTP UI) | http://localhost:8025 |
| MinIO console | http://localhost:9001 |
| Qdrant dashboard | http://localhost:6333/dashboard |
| Postgres | localhost:5432 |

## Quick start — hybrid dev loop

Run dependencies in Docker, run `api` and `web` on the host for fast reload:

```bash
make up-deps                          # only postgres + qdrant + minio + mailhog
make api-dev                          # uv run uvicorn app.main:app --reload --port 8000
pnpm -C web dev                       # next dev on :3000, proxies /api → :8000
```

## Configuration

All configuration is via env vars; see `.env.example` for the full list. Minimum to boot:

| Var | Source | Required | Example |
| --- | --- | --- | --- |
| `OLLAMA_API_KEYS` | api | **yes** | `key1\nkey2\nkey3` (newline or comma) |
| `OLLAMA_BASE_URL` | api | no | `https://ollama.com` |
| `OLLAMA_MODEL` | api | no | `gpt-oss:120b` |
| `DATABASE_URL` | api | yes | `postgresql+asyncpg://cpa:cpa@postgres:5432/cpa` |
| `QDRANT_URL` | api | yes | `http://qdrant:6333` |
| `S3_ENDPOINT_URL` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET` | api | yes | MinIO defaults in compose |
| `JWT_SECRET` | api | yes | 32+ random bytes (base64) |
| `SMTP_HOST` / `SMTP_PORT` | api | yes | `mailhog:1025` in dev |
| `AUTH_SECRET` | web | yes | 32+ random bytes |
| `AUTH_URL` | web | yes | `http://localhost:8080` |
| `INTERNAL_API_BASE` | web | yes | `http://api:8000` |
| `NEXT_PUBLIC_API_BASE` | web | yes | `/api` |

## Working with data

```bash
make ingest SOURCE=fasb_asc_public          # ingest one standards source
scripts/seed_fixture_engagement.sh          # upload a fixture TB+GL+bank into a demo engagement
make nuke                                   # drop all volumes and re-seed from scratch
```

## Common workflows

| I want to… | Open | Expected |
| --- | --- | --- |
| Try the chat | `/engagements/{eid}/chat` | Streamed answer with citation chips; click a chip to see the quoted paragraph |
| Upload and parse a TB | `/engagements/{eid}/documents` | Drag-drop, live parse status, parsed grid preview |
| Draw an audit sample | `/engagements/{eid}/audit/samples` | Sample IDs + reproducible seed printed |
| Generate a workpaper | `/engagements/{eid}/audit/workpapers` | Markdown + PDF download |
| Switch to Hebrew | Topbar language toggle | UI flips to RTL, HE prompts active |

## Running tests

```bash
make test-unit             # python unit tests (KeyRotator, ratios, sampling, …)
make test-int              # python integration tests (testcontainers: postgres + qdrant + minio)
pnpm -C web test           # vitest + React Testing Library
pnpm -C web e2e            # Playwright (needs `make up` first)
make e2e                   # full-stack: compose up → migrate → ingest fixture → Playwright
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `503 AllKeysExhausted` from `/query` or `/agent` | Check `OLLAMA_API_KEYS` is loaded; `make rotator-status` shows per-key state |
| `parsed_status=failed` on a file | Open `parsed_summary` in the row; for HE PDFs ensure Tesseract `heb` pack is in the api image |
| Auth.js cookie not set after login | `AUTH_URL` must match the host you visit; set `AUTH_TRUST_HOST=true` in dev |
| SSE not streaming through Caddy | Confirm `flush_interval` in `Caddyfile` |
| Hot reload of api inside compose is slow | Use the hybrid dev loop (`make up-deps` + `make api-dev`) |

## Project structure

```
app/         # FastAPI backend (Python 3.12)
web/         # Next.js 15 frontend (TypeScript)
charts/      # Helm chart (single chart, two Deployments)
config/      # standards sources, prompts, COA templates, workpaper templates
tests/       # unit + integration + contract + e2e (backend)
scripts/     # dev_up.sh, gen_openapi.py, seed scripts
docker/      # api Dockerfile + entrypoint
deploy/      # kind cluster config + per-cloud deploy notes
migrations/  # Alembic
```

See [`web/README.md`](web/README.md) and [`app/README.md`](app/README.md) for tier-specific dev loops.

## Deployment

- **Free, click-through deploy on Render** — see [`deploy/render.md`](deploy/render.md). Connect the repo, click "New Blueprint", paste your `OLLAMA_API_KEYS` + Qdrant Cloud credentials, get a public URL. No CLI required.
- **Production K8s** — kind smoke install + EKS/GKE/AKS notes live in [`deploy/README.md`](deploy/README.md); values in `charts/cpa/values-prod.yaml`.

## Licensing & sources

FASB ASC and IFRS Standards full text are paywalled. We auto-fetch only public excerpts (exposure drafts, basis-for-conclusions, topic outlines, project pages), government-published Hebrew standards, ITA circulars, public US IRC text (Cornell LII), and IRS publications. Organizations may supply their own licensed copies via authenticated upload. The fetcher honors `robots.txt` and per-host crawl-delay and sets a contact-bearing user agent. Live source state is visible at `/sources` in the running app.

## Contributing

- Pre-commit (`pre-commit install`) runs Ruff + mypy + ESLint + Prettier + OpenAPI drift check.
- Conventional Commits (`feat:`, `fix:`, `chore:`, …).
- Tests must pass; new endpoints must come with contract + integration tests.
- License: see [LICENSE](LICENSE).
