/**
 * Browser-callable proxy to FastAPI.
 *
 * Reads the access token from the server-side session and forwards it as
 * Authorization: Bearer. The browser never sees the JWT — it only sets
 * the encrypted Auth.js cookie via login.
 */

import { NextRequest, NextResponse } from "next/server";

import { auth } from "@/lib/auth";

const API_BASE = process.env.INTERNAL_API_BASE ?? "http://localhost:8000";

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const session = await auth();
  const { path } = await ctx.params;
  const search = req.nextUrl.search;
  const url = `${API_BASE}/${path.join("/")}${search}`;

  const headers = new Headers();
  // Forward only safe headers.
  const ct = req.headers.get("content-type");
  if (ct) headers.set("content-type", ct);
  if (session?.accessToken) headers.set("authorization", `Bearer ${session.accessToken}`);

  const init: RequestInit = {
    method: req.method,
    headers,
    body: ["GET", "HEAD"].includes(req.method) ? undefined : req.body,
    // @ts-expect-error: Node fetch needs duplex for streaming bodies
    duplex: "half",
    cache: "no-store",
  };
  const upstream = await fetch(url, init);
  const respHeaders = new Headers();
  upstream.headers.forEach((v, k) => respHeaders.set(k, v));
  return new NextResponse(upstream.body, { status: upstream.status, headers: respHeaders });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
export const PUT = forward;
export const DELETE = forward;
