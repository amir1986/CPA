/**
 * Browser-callable SSE proxy.
 *
 * Streams the upstream FastAPI SSE response (e.g. /query/stream) back to
 * the client while injecting Authorization: Bearer from the server-side
 * session. Critical that this stays a Node runtime route (default) — the
 * Edge runtime can mangle SSE under some configurations.
 */

import { NextRequest, NextResponse } from "next/server";

import { auth } from "@/lib/auth";

const API_BASE = (process.env.INTERNAL_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  // The login flow was removed: `auth()` returns a stub session whose
  // `accessToken` is always undefined, so the api now resolves every
  // request to the shared demo user (see app/api/auth.py::current_principal).
  // Gating on a token here made the whole Chat feature 401 on every message.
  // Forward unauthenticated and only attach a bearer if one ever exists,
  // matching the comparison proxy.
  const session = await auth();
  const { path } = await ctx.params;
  const url = `${API_BASE}/${path.join("/")}`;
  const body = await req.text();
  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "text/event-stream",
  };
  if (session?.accessToken) {
    headers.authorization = `Bearer ${session.accessToken}`;
  }
  const upstream = await fetch(url, {
    method: "POST",
    headers,
    body,
    cache: "no-store",
  });
  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      "x-accel-buffering": "no",
    },
  });
}
