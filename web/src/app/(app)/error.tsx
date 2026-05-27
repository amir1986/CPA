"use client";

import Link from "next/link";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

// Catch-all error boundary for everything under the (app) route group —
// engagements, sources, admin, usgaap-ifrs (its own /[runId]/error.tsx
// takes precedence for the run-detail page). Without this, RSC failures
// (e.g. apiFetch throwing because the cpa-api is cold-starting after a
// redeploy) render Next.js's opaque "Application error: a server-side
// exception has occurred (Digest: …)" page, which gives the user
// nothing actionable.
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const locale = useLocale();
  useEffect(() => {
    console.error("[(app)/error.tsx]", error);
  }, [error]);

  return (
    <div className="mx-auto max-w-2xl py-12">
      <div
        className="rounded-md border border-danger bg-danger/5 p-5 text-sm"
        data-testid="app-error-boundary"
      >
        <p className="text-base font-medium text-danger">
          {t("common.app_error_title", locale)}
        </p>
        <p className="mt-2 text-fg-muted">{t("common.app_error_hint", locale)}</p>
        {error.message ? (
          <p className="mt-3 whitespace-pre-wrap font-mono text-xs text-fg-subtle">
            {error.message}
            {error.digest ? `\n\ndigest: ${error.digest}` : ""}
          </p>
        ) : null}
        <div className="mt-4 flex gap-2">
          <Button size="sm" onClick={() => reset()}>
            {t("common.retry", locale)}
          </Button>
          <Link href="/engagements">
            <Button size="sm" variant="outline">
              {t("common.back", locale)}
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
