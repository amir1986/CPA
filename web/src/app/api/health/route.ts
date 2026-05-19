import { NextResponse } from "next/server";

export async function GET() {
  const apiBase = process.env.INTERNAL_API_BASE ?? "http://localhost:8000";
  try {
    const res = await fetch(`${apiBase}/healthz`, { cache: "no-store" });
    if (!res.ok) {
      return NextResponse.json({ ok: false, api: "unreachable" }, { status: 503 });
    }
    return NextResponse.json({ ok: true });
  } catch {
    return NextResponse.json({ ok: false, api: "unreachable" }, { status: 503 });
  }
}
