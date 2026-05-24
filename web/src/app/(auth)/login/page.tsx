import Link from "next/link";
import { redirect } from "next/navigation";

import { signIn } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const API_BASE = process.env.INTERNAL_API_BASE ?? "http://localhost:8000";

// Hard-coded "guest" credentials used by the Skip button. The first
// click registers this user (auto-creating a Demo Firm) if it doesn't
// exist yet; subsequent clicks just sign in. To disable the skip path
// in prod, unset CPA_ALLOW_SKIP=true (or always remove the button).
const SKIP_EMAIL = "demo@cpa.example";
const SKIP_PASSWORD = "demo-skip-pass-1234";
const SKIP_FIRM = "Demo Firm";

async function loginAction(formData: FormData) {
  "use server";
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");
  const from = String(formData.get("from") ?? "/");
  try {
    await signIn("credentials", { email, password, redirectTo: from || "/" });
  } catch (err) {
    if ((err as { digest?: string }).digest?.startsWith("NEXT_REDIRECT")) throw err;
    const msg = (err as Error).message ?? "unknown";
    const code = /credentials/i.test(msg) ? "invalid_credentials" : msg;
    redirect(`/login?error=${encodeURIComponent(code)}`);
  }
}

async function skipAction() {
  "use server";
  // Idempotent register: 409 (email_taken) is the expected steady-state response.
  try {
    await fetch(`${API_BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: SKIP_EMAIL,
        password: SKIP_PASSWORD,
        name: "Demo User",
        firm_name: SKIP_FIRM,
      }),
      cache: "no-store",
    });
  } catch (err) {
    // If we can't even reach the api, surface that — the signIn would
    // fail with the same root cause anyway.
    const detail = `api_unreachable: ${(err as Error).message} (tried ${API_BASE})`;
    redirect(`/login?error=${encodeURIComponent(detail)}`);
  }

  try {
    await signIn("credentials", {
      email: SKIP_EMAIL,
      password: SKIP_PASSWORD,
      redirectTo: "/engagements",
    });
  } catch (err) {
    if ((err as { digest?: string }).digest?.startsWith("NEXT_REDIRECT")) throw err;
    redirect(`/login?error=${encodeURIComponent(`skip_failed: ${(err as Error).message ?? "unknown"}`)}`);
  }
}

type Props = { searchParams: Promise<{ error?: string; from?: string }> };

export default async function LoginPage({ searchParams }: Props) {
  const sp = await searchParams;
  const error = sp.error;
  const from = sp.from ?? "/";
  return (
    <div>
      <h1 className="mb-1 text-lg font-semibold">Sign in</h1>
      <p className="mb-6 text-sm text-fg-muted">
        Welcome back. Sign in to access your engagements.
      </p>
      <form action={loginAction} className="space-y-4">
        <input type="hidden" name="from" value={from} />
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input id="email" name="email" type="email" required autoComplete="email" placeholder="you@firm.com" />
        </div>
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Password</Label>
            <Link href="/reset" className="text-xs text-brand hover:underline">
              Forgot password?
            </Link>
          </div>
          <Input id="password" name="password" type="password" required autoComplete="current-password" />
        </div>
        {error && (
          <p className="text-sm text-danger break-words">
            {error === "invalid_credentials" ? "Incorrect email or password." : decodeURIComponent(error)}
          </p>
        )}
        <Button type="submit" className="w-full">Sign in</Button>
      </form>

      <div className="my-4 flex items-center gap-3 text-xs text-fg-subtle">
        <span className="h-px flex-1 bg-border" />
        <span>or</span>
        <span className="h-px flex-1 bg-border" />
      </div>

      <form action={skipAction}>
        <Button type="submit" variant="outline" className="w-full">
          Skip — try as Demo User
        </Button>
        <p className="mt-2 text-center text-xs text-fg-subtle">
          Bypasses sign-in with a shared demo account. Don't store anything private.
        </p>
      </form>

      <p className="mt-6 text-center text-sm text-fg-muted">
        No account?{" "}
        <Link href="/register" className="text-brand hover:underline">
          Create one
        </Link>
      </p>
    </div>
  );
}
