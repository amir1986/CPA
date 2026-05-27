# `web/` — Next.js frontend

Polished, bilingual (EN + HE, RTL-aware) UI for the CPA AI Assistant. App Router + RSC + standalone Node runtime.

## Dev loop

```bash
pnpm install
pnpm dev                # next dev on :3000, proxies /api → INTERNAL_API_BASE (default :8000)
```

Pair with the api running on host:

```bash
# in repo root
make up-deps            # postgres + qdrant + minio + mailhog
make api-dev            # uvicorn on :8000
# here
pnpm dev
```

## Scripts

| Command | What |
| --- | --- |
| `pnpm dev` | Next.js dev server with hot reload |
| `pnpm build` | Production build (`output: standalone`) |
| `pnpm start` | Serve the standalone build |
| `pnpm lint` | ESLint |
| `pnpm format` | Prettier write |
| `pnpm test` | vitest unit tests |
| `pnpm e2e` | Playwright (requires `make up` first) |
| `pnpm gen:api` | Generate typed client from `http://localhost:8000/openapi.json` |
| `pnpm typecheck` | `tsc --noEmit` |

## Environment

See `.env.example`. The web container reads `INTERNAL_API_BASE` (server-side cluster DNS) and the browser reads `NEXT_PUBLIC_API_BASE` (path under the Ingress, default `/api`).

## Layout

```
src/
├── app/
│   ├── (auth)/             # login, register, verify, reset
│   ├── (app)/              # authenticated app shell
│   ├── api/                # Auth.js + SSE proxy + health
│   └── layout.tsx          # HTML shell + providers
├── components/
│   ├── ui/                 # shadcn primitives
│   ├── app-shell/          # sidebar, topbar, command palette
│   └── …                   # chat, docs, books, audit, …
├── lib/                    # api client, auth, i18n, tokens, format
└── styles/                 # design tokens (CSS custom properties)
```

## Design system

Tokens live in [`src/styles/tokens.css`](src/styles/tokens.css) (light + dark via `data-theme`). Tailwind maps them in [`tailwind.config.ts`](tailwind.config.ts) — components reference semantic names (`bg-bg`, `text-fg-muted`, `border-border-strong`), never raw hex.

Motion respects `prefers-reduced-motion`; focus rings are visible by default; layout uses Tailwind logical properties (`ps-*`, `start-*`) so RTL works without per-locale forks.
