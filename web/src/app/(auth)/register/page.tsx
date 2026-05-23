import Link from "next/link";
import { redirect } from "next/navigation";

import { signIn } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const API_BASE = process.env.INTERNAL_API_BASE ?? "http://localhost:8000";

async function registerAction(formData: FormData) {
  "use server";
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");
  const firm_name = String(formData.get("firm_name") ?? "");
  const name = String(formData.get("name") ?? "");

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, firm_name, name: name || null }),
      cache: "no-store",
    });
  } catch (err) {
    const detail = `api_unreachable: ${(err as Error).message} (tried ${API_BASE})`;
    redirect(`/register?error=${encodeURIComponent(detail)}`);
  }

  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string; title?: string };
    const code = body.title ?? "register_failed";
    redirect(`/register?error=${encodeURIComponent(code)}`);
  }

  // Auto sign-in: NextAuth will re-call the backend /auth/login.
  // signIn throws NEXT_REDIRECT on success — rethrow so Next handles it.
  try {
    await signIn("credentials", { email, password, redirectTo: "/engagements" });
  } catch (err) {
    if ((err as { digest?: string }).digest?.startsWith("NEXT_REDIRECT")) throw err;
    const detail = `signin_failed: ${(err as Error).message ?? "unknown"}`;
    redirect(`/register?error=${encodeURIComponent(detail)}`);
  }
}

type Props = { searchParams: Promise<{ error?: string }> };

export default async function RegisterPage({ searchParams }: Props) {
  const sp = await searchParams;
  return (
    <div>
      <h1 className="mb-1 text-lg font-semibold">Create an account</h1>
      <p className="mb-6 text-sm text-fg-muted">Set up your firm workspace.</p>
      <form action={registerAction} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="email">Work email</Label>
          <Input id="email" name="email" type="email" required autoComplete="email" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="name">Your name</Label>
          <Input id="name" name="name" autoComplete="name" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="firm">Firm name</Label>
          <Input id="firm" name="firm_name" required autoComplete="organization" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input id="password" name="password" type="password" required minLength={12} autoComplete="new-password" />
        </div>
        {sp.error && (
          <p className="text-sm text-danger break-words">
            {decodeURIComponent(sp.error)}
          </p>
        )}
        <Button type="submit" className="w-full">Create account</Button>
      </form>
      <p className="mt-6 text-center text-sm text-fg-muted">
        Already have one?{" "}
        <Link href="/login" className="text-brand hover:underline">Sign in</Link>
      </p>
    </div>
  );
}
