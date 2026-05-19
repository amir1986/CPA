import { signOut } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api/client";
import type { User } from "@/lib/api/types";

async function logoutAction() {
  "use server";
  await signOut({ redirectTo: "/login" });
}

export default async function ProfilePage() {
  const me = await apiFetch<User>("/auth/me");
  return (
    <div className="mx-auto max-w-xl">
      <h1 className="mb-1 text-xl font-semibold">Profile</h1>
      <p className="mb-4 text-sm text-fg-muted">Your account on this firm.</p>
      <section className="space-y-3 rounded-lg border border-border bg-bg p-5">
        <Row label="Email" value={me.email} />
        <Row label="Name" value={me.name ?? "—"} />
        <Row label="Role" value={me.role} />
        <Row label="Locale" value={me.locale} />
        <Row label="Firm ID" value={me.firm_id} />
        <Row label="Email verified" value={me.email_verified ? "yes" : "no"} />
      </section>
      <form action={logoutAction} className="mt-5">
        <Button type="submit" variant="outline">Sign out</Button>
      </form>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs uppercase tracking-wide text-fg-subtle">{label}</span>
      <span className="font-mono text-sm">{value}</span>
    </div>
  );
}
