"use client";

import { useState, useTransition } from "react";
import { Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

const LABELS: Record<"en" | "he", string> = {
  en: "English",
  he: "עברית (Hebrew, RTL)",
};

export function LocaleSelect({ current }: { current: string }) {
  const router = useRouter();
  const ctxLocale = useLocale();
  const tr = (k: string) => t(k, ctxLocale);
  const [pick, setPick] = useState<"en" | "he">(
    current === "he" ? "he" : "en",
  );
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function save() {
    setError(null);
    setSaved(false);
    startTransition(async () => {
      const res = await fetch("/api/auth/me/locale", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ locale: pick }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        setError(body.detail ?? `save failed (${res.status})`);
        return;
      }
      // Persist a client-readable cookie so the next SSR pass can set
      // <html dir="rtl"> immediately, without an extra round-trip.
      document.cookie = `cpa_locale=${pick}; path=/; max-age=31536000; SameSite=Lax`;
      setSaved(true);
      // Apply RTL to the live document so the change is visible right away.
      document.documentElement.lang = pick;
      document.documentElement.dir = pick === "he" ? "rtl" : "ltr";
      // Re-render the tree so server components pick up the new locale.
      router.refresh();
    });
  }

  return (
    <div className="space-y-2" data-testid="locale-select">
      <label className="block text-xs uppercase tracking-wide text-fg-subtle">
        {tr("settings.language")}
      </label>
      <div className="flex items-center gap-2">
        <select
          value={pick}
          onChange={(e) => {
            setPick(e.target.value as "en" | "he");
            setSaved(false);
          }}
          className="rounded-md border border-border bg-bg-elev px-3 py-1.5 text-sm"
        >
          {(["en", "he"] as const).map((k) => (
            <option key={k} value={k}>
              {LABELS[k]}
            </option>
          ))}
        </select>
        <Button size="sm" onClick={save} disabled={pending || pick === current}>
          {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {saved && pick === current ? tr("settings.saved") : tr("settings.save")}
        </Button>
        {error && <span className="text-sm text-danger">{error}</span>}
      </div>
      <p className="text-xs text-fg-muted">{tr("settings.language_hint")}</p>
    </div>
  );
}
