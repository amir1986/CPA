# `app/` — FastAPI backend

Knowledge + books + analysis + audit, with strict citations and a deterministic REST surface.

## Dev loop

```bash
uv sync                     # install python deps
uv run uvicorn app.main:app --reload --port 8000
```

Pair with deps in Docker:

```bash
# in repo root
make up-deps                # postgres + qdrant + minio + mailhog
make api-dev                # same as the uvicorn line above
```

## Scripts

| Command | What |
| --- | --- |
| `make migrate` | `alembic upgrade head` |
| `make seed` | migrate + ingest fixture standards + seed dev firm/user |
| `make ingest SOURCE=fasb_asc_public` | Run one standards-ingest source |
| `make rotator-status` | Print live `KeyRotator` state |
| `make test-unit` | pytest unit tests |
| `make test-int` | pytest integration tests (testcontainers) |
| `make openapi` | Dump `openapi.json` into `spec/` |

## Environment

See `../.env.example`. Most relevant:

- `OLLAMA_API_KEYS` — newline/comma-separated (or `OLLAMA_API_KEYS_FILE`)
- `DATABASE_URL` — `postgresql+asyncpg://…`
- `QDRANT_URL`, `S3_*`, `JWT_SECRET`, `SMTP_*`

## Layout

```
app/
├── main.py                 # FastAPI factory; lifespan: DB, S3, Qdrant, LLM, embed
├── config.py               # pydantic-settings
├── api/routes/             # one router per area (health, auth, engagements, …)
├── llm/ollama_rotator.py   # circular KeyRotator (pure logic, tested)
├── llm/ollama_client.py    # httpx client that consults the rotator
├── rag/                    # standards-corpus retrieval + citation validator
├── ingest_standards/       # public standards corpora fetch/parse/chunk/embed
├── ingest_docs/            # per-engagement uploads (TB/GL/bank/invoice/PDF/OCR)
├── coa/, categorize/, reconcile/, analyze/, audit/   # deterministic services
└── agent/                  # LlamaIndex FunctionAgent + tool wrappers
```

## Key invariants

- **Multi-tenant by construction** — every repository method takes `firm_id`; cross-firm path params return 404.
- **Citations are validated**, not trusted — the LLM's JSON output is filtered against retrieved nodes; empty after validation → refusal.
- **Audit is deterministic** — sampling persists the seed + population query; reruns reproduce IDs exactly.
- **Categorization never auto-posts** — LLM outputs are suggestions; the learner promotes accepted mappings to rules.
