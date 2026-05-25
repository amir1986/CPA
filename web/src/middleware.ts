import { NextResponse } from "next/server";

// Login flow removed — every page is public. Middleware is left in place
// for future use (rate limiting, locale routing, etc.) but currently
// passes through unchanged.
export default function middleware() {
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon|api/cpa|api/stream|.*\\.svg).*)"],
};
