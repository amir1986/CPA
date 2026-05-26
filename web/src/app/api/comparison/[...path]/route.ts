import { NextRequest, NextResponse } from "next/server";

const API_BASE = (process.env.INTERNAL_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  const search = req.nextUrl.search;
  const url = `${API_BASE}/comparison/${path.join("/")}${search}`;

  const headers = new Headers();
  for (const key of ["accept", "content-type"]) {
    const value = req.headers.get(key);
    if (value) headers.set(key, value);
  }

  const upstream = await fetch(url, {
    method: req.method,
    headers,
    body: ["GET", "HEAD"].includes(req.method) ? undefined : req.body,
    // @ts-expect-error: Node fetch requires duplex for streaming uploads.
    duplex: "half",
    cache: "no-store",
  });

  const respHeaders = new Headers();
  upstream.headers.forEach((value, key) => respHeaders.set(key, value));
  return new NextResponse(upstream.body, { status: upstream.status, headers: respHeaders });
}

export const GET = forward;
export const POST = forward;
export const PATCH = forward;
