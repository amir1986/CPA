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
  const session = await auth();
  if (!session?.accessToken) {
    return NextResponse.json({ detail: "unauthorized" }, { status: 401 });
  }
  const { path } = await ctx.params;
  const url = `${API_BASE}/${path.join("/")}`;
  const body = await req.text();
  const upstream = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${session.accessToken}`,
      accept: "text/event-stream",
    },
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
