import { NextRequest, NextResponse } from "next/server";

const API_BASE = (process.env.INTERNAL_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");

// Render's free tier spins cpa-api down after ~15 min idle. The first
// request after that triggers a 30-60 s cold-start during which the
// upstream fetch can throw (ECONNREFUSED, connect timeout) before the
// uvicorn worker is ready. Without retry the user saw the export 500
// the first time and succeed on retry — fix is to absorb 1-2 transient
// failures here so the user never sees the cold-start window.
const COLD_START_RETRIES = 3;
const COLD_START_BACKOFF_MS = [800, 2000, 4000];

// Streaming endpoints (SSE) MUST NOT be retried — they hold the
// connection open and any "failure" we'd see is actually the long-lived
// stream the client wants to keep reading. Only retry one-shot
// endpoints where a transient connect error is meaningful.
function isStreamingPath(path: string[]): boolean {
  return path[path.length - 1] === "stream";
}

// Idempotent endpoints we can safely retry on ANY 5xx (not just the
// "transient 500 with no body" heuristic). `export` only reads the run +
// renders a memo — no writes, no side effects — so re-issuing it is safe
// and is exactly what cures the "first PDF/memo click 500s, second click
// works" cold-start symptom: the first request hits cpa-api mid-wake
// (or during the first cold Ollama translation call) and 500s with a
// problem+json body that the transient-500 heuristic would NOT retry.
// Retrying server-side inside the one request means the user never sees
// that first-attempt failure.
function isIdempotentRetryable(path: string[]): boolean {
  return path[path.length - 1] === "export";
}

// Multipart uploads (create_run) can be ~500 MB total — buffering them
// for retry would OOM the 512 MB Next process. Skip retry for these and
// fall back to a single streaming attempt. Endpoints with tiny JSON
// bodies (framework override, export) are safe to buffer + retry.
function canBufferBody(req: NextRequest): boolean {
  const ct = (req.headers.get("content-type") ?? "").toLowerCase();
  if (ct.startsWith("multipart/")) return false;
  const len = Number(req.headers.get("content-length") ?? "0");
  // 1 MB cap is generous for JSON bodies; anything larger doesn't get
  // retried (better to surface the upstream error than OOM the proxy).
  return len === 0 || len <= 1_000_000;
}

function upstreamUnavailable(detail: string): Response {
  return NextResponse.json(
    {
      type: "about:blank/upstream_unavailable",
      title: "upstream_unavailable",
      status: 503,
      detail,
    },
    { status: 503, headers: { "content-type": "application/problem+json" } },
  );
}

// A bare 500 with no problem+json body is a strong signal the upstream
// died mid-response or uvicorn raised before our handler could format an
// error envelope. Re-fetching almost always works — exactly the pattern
// the user reported ("first click 500s, retry works"). A 500 WITH a
// detail field is a real application error and must NOT be retried (it
// would mask the message and double the latency).
async function isTransient500(res: Response): Promise<boolean> {
  if (res.status !== 500) return false;
  const ct = (res.headers.get("content-type") ?? "").toLowerCase();
  // Real app errors come back as application/problem+json with a detail.
  // Anything else (text/plain "Internal Server Error", text/html edge
  // page, empty body) is the symptom of an escaped panic / worker death.
  if (!ct.includes("json")) return true;
  try {
    const clone = res.clone();
    const body = (await clone.json()) as { detail?: unknown };
    return !body || typeof body.detail !== "string" || body.detail.length === 0;
  } catch {
    return true;
  }
}

async function fetchWithRetry(
  url: string,
  init: RequestInit,
  retries: number,
  retryAny5xx = false,
): Promise<Response> {
  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url, init);
      const transient =
        res.status === 502 ||
        res.status === 503 ||
        res.status === 504 ||
        // For idempotent endpoints (export), retry on ANY 5xx — a
        // cold-start crash 500s with a problem+json body that the
        // transient-500 heuristic deliberately skips.
        (retryAny5xx && res.status >= 500) ||
        (await isTransient500(res));
      if (attempt < retries && transient) {
        await new Promise((r) => setTimeout(r, COLD_START_BACKOFF_MS[attempt] ?? 4000));
        continue;
      }
      return res;
    } catch (err) {
      lastErr = err;
      if (attempt >= retries) break;
      await new Promise((r) => setTimeout(r, COLD_START_BACKOFF_MS[attempt] ?? 4000));
    }
  }
  return upstreamUnavailable(
    `cpa-api did not respond after ${retries + 1} attempts — Render's free tier may be cold-starting. Try again in 30 seconds. (last error: ${lastErr instanceof Error ? lastErr.message : String(lastErr)})`,
  );
}

async function forward(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await ctx.params;
  const search = req.nextUrl.search;
  const url = `${API_BASE}/comparison/${path.join("/")}${search}`;

  const headers = new Headers();
  for (const key of ["accept", "content-type"]) {
    const value = req.headers.get(key);
    if (value) headers.set(key, value);
  }

  const streaming = isStreamingPath(path);
  const hasBody = !["GET", "HEAD"].includes(req.method);
  const bufferable = hasBody && canBufferBody(req);

  // Streaming + un-retryable bodies (multipart uploads) go through a
  // single attempt with the raw request body stream. Replaying that
  // stream isn't possible and OOM-ing the proxy by buffering 500 MB
  // multipart uploads isn't acceptable either.
  if (streaming || (hasBody && !bufferable)) {
    const init: RequestInit = {
      method: req.method,
      headers,
      body: hasBody ? req.body : undefined,
      // @ts-expect-error: Node fetch requires duplex for streaming uploads.
      duplex: "half",
      cache: "no-store",
    };
    let upstream: Response;
    try {
      upstream = await fetch(url, init);
    } catch (err) {
      upstream = upstreamUnavailable(
        `cpa-api unreachable: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
    const respHeaders = new Headers();
    upstream.headers.forEach((value, key) => respHeaders.set(key, value));
    return new NextResponse(upstream.body, { status: upstream.status, headers: respHeaders });
  }

  // Small-body / no-body path: buffer once so we can replay on cold-start
  // retries. Every export / framework-override / list call goes through
  // here, so this is the path that the user's "first PDF click fails"
  // bug travels through.
  const body = hasBody ? await req.arrayBuffer() : undefined;
  const init: RequestInit = { method: req.method, headers, body, cache: "no-store" };

  const upstream = await fetchWithRetry(
    url, init, COLD_START_RETRIES, isIdempotentRetryable(path),
  );
  const respHeaders = new Headers();
  upstream.headers.forEach((value, key) => respHeaders.set(key, value));
  return new NextResponse(upstream.body, { status: upstream.status, headers: respHeaders });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
