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

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    refreshToken?: string;
    backendUser?: User;
    accessTokenExpiresAt?: number;
  }
}

const API_BASE = process.env.INTERNAL_API_BASE ?? "http://localhost:8000";

async function backendLogin(email: string, password: string): Promise<LoginOut | null> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as LoginOut;
}

async function backendRefresh(refreshToken: string): Promise<{ access_token: string; refresh_token: string } | null> {
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
    const json = JSON.parse(Buffer.from(payloadB64, "base64").toString("utf-8")) as { exp?: number };
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
      // Initial sign-in: persist tokens and user info into the JWT.
      if (user) {
        const u = user as unknown as {
          backendAccess?: string;
          backendRefresh?: string;
          backendUser?: User;
        };
        token.accessToken = u.backendAccess;
        token.refreshToken = u.backendRefresh;
        token.backendUser = u.backendUser;
        token.accessTokenExpiresAt = u.backendAccess ? decodeExpiry(u.backendAccess) : undefined;
        return token;
      }
      // Refresh ~30s before expiry.
      const now = Math.floor(Date.now() / 1000);
      if (token.accessToken && token.accessTokenExpiresAt && now > token.accessTokenExpiresAt - 30) {
        if (!token.refreshToken) return token;
        const refreshed = await backendRefresh(token.refreshToken);
        if (refreshed) {
          token.accessToken = refreshed.access_token;
          token.refreshToken = refreshed.refresh_token;
          token.accessTokenExpiresAt = decodeExpiry(refreshed.access_token);
        }
      }
      return token;
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken;
      if (token.backendUser) {
        session.user = {
          ...session.user,
          id: token.backendUser.id,
          email: token.backendUser.email,
          name: token.backendUser.name ?? token.backendUser.email,
          role: token.backendUser.role,
          firmId: token.backendUser.firm_id,
          locale: token.backendUser.locale,
        };
      }
      return session;
    },
  },
});
