import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  return (
    <div>
      <h1 className="mb-1 text-lg font-semibold">Sign in</h1>
      <p className="mb-6 text-sm text-fg-muted">
        Welcome back. Sign in to access your engagements.
      </p>
      <form action="/api/auth/callback/credentials" method="post" className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            placeholder="you@firm.com"
          />
        </div>
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Password</Label>
            <Link href="/reset" className="text-xs text-brand hover:underline">
              Forgot password?
            </Link>
          </div>
          <Input
            id="password"
            name="password"
            type="password"
            required
            autoComplete="current-password"
          />
        </div>
        <Button type="submit" className="w-full">
          Sign in
        </Button>
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
