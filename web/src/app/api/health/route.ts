import { NextResponse } from "next/server";

/**
 * Web liveness probe.
 *
 * This intentionally does NOT depend on the api being reachable —
 * Render's load balancer uses this to decide whether the web service
 * is alive. If we gated on the api, a sleeping cpa-api on free tier
 * would mark cpa-web as unhealthy (and Render would refuse to route
 * traffic to it), even though the web process itself is fine.
 *
 * For a "is the whole stack healthy?" check, hit /api/cpa/readyz —
 * that does check downstream deps.
 */
export async function GET() {
  return NextResponse.json({ ok: true });
}
