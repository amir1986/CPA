/**
 * Auth.js (NextAuth v5) configuration.
 *
 * Credentials provider that POSTs to FastAPI /auth/login and stores the
 * access+refresh tokens inside the encrypted Auth.js JWT cookie. The
 * browser never sees the tokens. Server-side fetches read the session
 * via `auth()` and attach `Authorization: Bearer ${access_token}`.
 */

import NextAuth, { type DefaultSession } from "next-auth";
import Credentials from "next-auth/providers/credentials";

import type { LoginOut, User } from "@/lib/api/types";

declare module "next-auth" {
  interface Session extends DefaultSession {
    accessToken?: string;
    user: DefaultSession["user"] & {
      id: string;
      role: string;
      firmId: string;
      locale: string;
    };
  }
}

// Local shape for the encrypted JWT. We avoid the next-auth/jwt module
// augmentation because v5's subpath-export module resolution makes the
// `declare module` form fragile at build time.
type AppJWT = {
  accessToken?: string;
  refreshToken?: string;
  backendUser?: User;
  accessTokenExpiresAt?: number;
  [key: string]: unknown;
};

const API_BASE = (process.env.INTERNAL_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");

async function backendLogin(email: string, password: string): Promise<LoginOut | null> {
  // Render free-tier spins down idle services after ~15 min — first request
  // after wake takes 30-60s and frequently 502s. Retry transient 5xx so the
  // user doesn't get bounced back to /login with skip_failed [login=502].
  const res = await fetchWithColdStartRetry(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as LoginOut;
}


async function fetchWithColdStartRetry(url: string, init: RequestInit): Promise<Response> {
  // ~90 s total budget — covers Render free-tier cold start AND a
  // mid-deploy restart window. Retries only on 502 / 503 / 504 (the
  // edge's "upstream not ready" signals) or fetch throws.
  const DELAYS_MS = [1500, 3000, 5000, 8000, 12000, 15000, 20000, 25000];
  let lastResp: Response | null = null;
  let lastErr: unknown = null;
  for (let i = 0; i <= DELAYS_MS.length; i++) {
    try {
      const resp = await fetch(url, init);
      lastResp = resp;
      if (resp.status >= 502 && resp.status <= 504) {
        if (i < DELAYS_MS.length) await new Promise((r) => setTimeout(r, DELAYS_MS[i]));
        continue;
      }
      return resp;
    } catch (err) {
      lastErr = err;
      if (i < DELAYS_MS.length) await new Promise((r) => setTimeout(r, DELAYS_MS[i]));
    }
  }
  if (lastResp) return lastResp;
  throw lastErr ?? new Error("request failed");
}

async function backendRefresh(
  refreshToken: string,
): Promise<{ access_token: string; refresh_token: string } | null> {
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as { access_token: string; refresh_token: string };
}

function decodeExpiry(token: string): number | undefined {
  try {
    const [, payloadB64] = token.split(".");
    const json = JSON.parse(Buffer.from(payloadB64, "base64").toString("utf-8")) as {
      exp?: number;
    };
    return json.exp;
  } catch {
    return undefined;
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  session: { strategy: "jwt", maxAge: 60 * 60 * 24 * 30 },
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(creds) {
        const email = String(creds?.email ?? "");
        const password = String(creds?.password ?? "");
        if (!email || !password) return null;
        const result = await backendLogin(email, password);
        if (!result) return null;
        return {
          id: result.user.id,
          email: result.user.email,
          name: result.user.name ?? result.user.email,
          // Stash backend payload so the jwt callback can persist it.
          ...({
            backendAccess: result.tokens.access_token,
            backendRefresh: result.tokens.refresh_token,
            backendUser: result.user,
          } as Record<string, unknown>),
        };
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      const t = token as AppJWT;
      // Initial sign-in: persist tokens and user info into the JWT.
      if (user) {
        const u = user as unknown as {
          backendAccess?: string;
          backendRefresh?: string;
          backendUser?: User;
        };
        t.accessToken = u.backendAccess;
        t.refreshToken = u.backendRefresh;
        t.backendUser = u.backendUser;
        t.accessTokenExpiresAt = u.backendAccess ? decodeExpiry(u.backendAccess) : undefined;
        return t;
      }
      // Refresh ~30s before expiry.
      const now = Math.floor(Date.now() / 1000);
      if (t.accessToken && t.accessTokenExpiresAt && now > t.accessTokenExpiresAt - 30) {
        if (!t.refreshToken) return t;
        const refreshed = await backendRefresh(t.refreshToken);
        if (refreshed) {
          t.accessToken = refreshed.access_token;
          t.refreshToken = refreshed.refresh_token;
          t.accessTokenExpiresAt = decodeExpiry(refreshed.access_token);
        }
      }
      return t;
    },
    async session({ session, token }) {
      const t = token as AppJWT;
      session.accessToken = t.accessToken;
      if (t.backendUser) {
        session.user = {
          ...session.user,
          id: t.backendUser.id,
          email: t.backendUser.email,
          name: t.backendUser.name ?? t.backendUser.email,
          role: t.backendUser.role,
          firmId: t.backendUser.firm_id,
          locale: t.backendUser.locale,
        };
      }
      return session;
    },
  },
});
