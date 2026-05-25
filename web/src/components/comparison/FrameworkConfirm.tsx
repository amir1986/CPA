"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

type Props = {
  runId: string;
  detected: "US" | "IFRS" | null;
  current: "US" | "IFRS" | null;
  confidence: number | null;
  rationale: string | null;
};

export function FrameworkConfirm({ runId, detected, current, confidence, rationale }: Props) {
  const router = useRouter();
  const locale = useLocale();
  const tr = (k: string, v?: Record<string, string | number>) => t(k, locale, v);
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState<"US" | "IFRS">(current ?? detected ?? "US");

  function save() {
    setError(null);
    startTransition(async () => {
      const res = await fetch(`/api/comparison/runs/${runId}/framework`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ framework: pick }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        setError(body.detail ?? "failed to save");
        return;
      }
      router.refresh();
    });
  }

  const confidencePct = confidence != null ? Math.round(confidence * 100) : null;

  return (
    <section
      className="rounded-lg border border-border bg-bg p-4"
      data-testid="framework-confirm"
    >
      <h2 className="text-sm font-medium">{tr("usgaap.detected_framework")}</h2>
      <div className="mt-2 flex items-baseline gap-3">
        <span className="text-2xl font-semibold" data-testid="detected-framework">
          {detected ?? "—"}
        </span>
        {confidencePct != null && (
          <span className="text-sm text-fg-muted" data-testid="detected-confidence">
            {tr("usgaap.confidence")}: {confidencePct}%
          </span>
        )}
      </div>
      {rationale && <p className="mt-1 text-xs text-fg-muted">{rationale}</p>}

      <fieldset className="mt-4 flex flex-wrap items-center gap-3">
        <legend className="sr-only">{tr("usgaap.override_framework")}</legend>
        {(["US", "IFRS"] as const).map((fw) => (
          <label key={fw} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="override"
              value={fw}
              checked={pick === fw}
              onChange={() => setPick(fw)}
            />
            <span>{fw === "US" ? tr("usgaap.us_gaap") : tr("usgaap.ifrs")}</span>
          </label>
        ))}
        <Button size="sm" onClick={save} disabled={pending}>
          {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {current === pick ? tr("usgaap.confirmed") : tr("usgaap.confirm")}
        </Button>
        {error && <span className="text-sm text-danger">{error}</span>}
      </fieldset>
    </section>
  );
}
