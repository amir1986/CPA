import { auth } from "@/lib/auth";
import { NextResponse } from "next/server";

const PUBLIC_PATHS = ["/login", "/register", "/verify", "/reset", "/api/auth", "/api/health"];

export default auth((req) => {
  const url = req.nextUrl;
  const isPublic = PUBLIC_PATHS.some((p) => url.pathname.startsWith(p));
  if (isPublic) return NextResponse.next();
  if (!req.auth) {
    const redirect = url.clone();
    redirect.pathname = "/login";
    redirect.searchParams.set("from", url.pathname);
    return NextResponse.redirect(redirect);
  }
  return NextResponse.next();
});

export const config = {
  // Skip static files + Next internals + the SSE proxy (which handles its own auth).
  matcher: ["/((?!_next/static|_next/image|favicon|api/cpa|api/stream|.*\\.svg).*)"],
};
