import Link from "next/link";
import { redirect } from "next/navigation";

import { signIn } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

async function loginAction(formData: FormData) {
  "use server";
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");
  const from = String(formData.get("from") ?? "/");
  try {
    await signIn("credentials", { email, password, redirectTo: from || "/" });
  } catch (err) {
    // NextAuth's redirect throws a NEXT_REDIRECT-shaped error on success;
    // re-throw so the redirect actually happens.
    if ((err as { digest?: string }).digest?.startsWith("NEXT_REDIRECT")) throw err;
    const msg = (err as Error).message ?? "unknown";
    // Surface the real error in dev/diagnostic; "invalid_credentials" for the
    // common 401 case. This includes the API URL on connection failures so
    // we can spot a missing INTERNAL_API_BASE from the UI.
    const code = /credentials/i.test(msg) ? "invalid_credentials" : msg;
    redirect(`/login?error=${encodeURIComponent(code)}`);
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
      <p className="mt-6 text-center text-sm text-fg-muted">
        No account?{" "}
        <Link href="/register" className="text-brand hover:underline">
          Create one
        </Link>
      </p>
    </div>
  );
}
