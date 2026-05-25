import { cookies } from "next/headers";

import { signOut } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { LocaleSelect } from "@/components/settings/LocaleSelect";
import { apiFetch } from "@/lib/api/client";
import type { User } from "@/lib/api/types";
import { t, type Locale } from "@/lib/i18n";

async function logoutAction() {
  "use server";
  await signOut({ redirectTo: "/login" });
}

export default async function ProfilePage() {
  const cookieStore = await cookies();
  const locale: Locale = cookieStore.get("cpa_locale")?.value === "he" ? "he" : "en";
  const tr = (k: string) => t(k, locale);
  const me = await apiFetch<User>("/auth/me");
  return (
    <div className="mx-auto max-w-xl">
      <h1 className="mb-1 text-xl font-semibold">{tr("settings.profile_title")}</h1>
      <p className="mb-4 text-sm text-fg-muted">{tr("settings.profile_subtitle")}</p>
      <section className="space-y-3 rounded-lg border border-border bg-bg p-5">
        <Row label={tr("settings.email")} value={me.email} />
        <Row label={tr("settings.name")} value={me.name ?? "—"} />
        <Row label={tr("settings.role")} value={me.role} />
        <Row label={tr("settings.firm_id")} value={me.firm_id} />
        <Row
          label={tr("settings.email_verified")}
          value={me.email_verified ? tr("settings.yes") : tr("settings.no")}
        />
      </section>
      <section className="mt-5 rounded-lg border border-border bg-bg p-5">
        <LocaleSelect current={me.locale} />
      </section>
      <form action={logoutAction} className="mt-5">
        <Button type="submit" variant="outline">
          {tr("settings.sign_out")}
        </Button>
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
