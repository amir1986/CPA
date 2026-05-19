/**
 * Server-only typed API client.
 *
 * Always called from server components / route handlers — the browser
 * never sees the access token, only the encrypted Auth.js cookie. To call
 * the backend from the browser, go through one of the wrapper Route
 * Handlers under `/api/cpa/*`.
 */

import { auth } from "@/lib/auth";

export type ProblemDetail = {
  type: string;
  title: string;
  status: number;
  detail: string;
  errors?: unknown;
};

export class ApiError extends Error {
  status: number;
  code: string;
  problem: ProblemDetail;

  constructor(problem: ProblemDetail) {
    super(problem.detail || problem.title);
    this.status = problem.status;
    this.code = problem.title;
    this.problem = problem;
  }
}

const API_BASE = process.env.INTERNAL_API_BASE ?? "http://localhost:8000";

type FetchOpts = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  /** Pre-supplied access token (e.g. during signin before a session exists). */
  token?: string;
  /** Allow caller to pass a FormData/Blob untouched. */
  rawBody?: BodyInit;
  signal?: AbortSignal;
  /** Override the cached session token resolution. */
  noAuth?: boolean;
};

async function getToken(): Promise<string | undefined> {
  const session = await auth();
  return session?.accessToken;
}

export async function apiFetch<T>(path: string, opts: FetchOpts = {}): Promise<T> {
  const token = opts.token ?? (opts.noAuth ? undefined : await getToken());
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(opts.headers ?? {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (opts.body !== undefined && !opts.rawBody) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method: opts.method ?? "GET",
    headers,
    body: opts.rawBody ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
    cache: "no-store",
    signal: opts.signal,
  });
  if (!res.ok) {
    let problem: ProblemDetail;
    try {
      problem = (await res.json()) as ProblemDetail;
    } catch {
      problem = { type: "about:blank", title: "http_error", status: res.status, detail: res.statusText };
    }
    throw new ApiError(problem);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function apiStream(path: string, body: unknown, opts: { signal?: AbortSignal } = {}): Promise<Response> {
  const token = await getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: opts.signal,
  });
}
