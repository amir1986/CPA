/**
 * Auth stub.
 *
 * The login flow was removed. Every request now resolves to the shared
 * demo user on the api side (see app/api/auth.py::current_principal).
 *
 * This module keeps the same exports as the old Auth.js setup so the
 * many call sites (`auth()`, `signIn()`, `signOut()`, route handlers
 * importing `handlers`) don't all need to be rewritten — they just get
 * no-op implementations.
 */

type FakeSession = {
  user: { email: string; name: string; locale: string } | null;
  accessToken: undefined;
  refreshToken: undefined;
};

const FAKE_SESSION: FakeSession = {
  user: { email: "demo@cpa.example", name: "Demo User", locale: "he" },
  accessToken: undefined,
  refreshToken: undefined,
};

export async function auth(): Promise<FakeSession> {
  return FAKE_SESSION;
}

export async function signIn(
  _provider?: string,
  _credentials?: Record<string, unknown>,
): Promise<void> {
  // No-op — the api accepts every request as the demo user already.
}

export async function signOut(opts?: { redirectTo?: string }): Promise<void> {
  // Best-effort: bounce to the target URL if given. Real session teardown
  // isn't necessary since there's no session to tear down.
  if (typeof window !== "undefined" && opts?.redirectTo) {
    window.location.href = opts.redirectTo;
  }
}

// Stub for the old /api/auth/[...nextauth] route handler — returns 404.
async function notFound(): Promise<Response> {
  return new Response("auth disabled", { status: 404 });
}

export const handlers = {
  GET: notFound,
  POST: notFound,
};
