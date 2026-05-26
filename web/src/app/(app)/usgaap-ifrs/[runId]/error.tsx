"use client";

import { useEffect } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

// Route-level error boundary for /usgaap-ifrs/[runId]. Without this, any
// unexpected error during render produces Next's opaque "Application
// error: a server-side exception has occurred (Digest: …)" page, which
// gives the user nothing actionable.
export default function RunDetailError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const locale = useLocale();
  useEffect(() => {
    console.error("[/usgaap-ifrs/[runId]/error.tsx]", error);
  }, [error]);

  return (
    <div className="mx-auto max-w-3xl space-y-4" data-testid="run-detail-boundary">
      <Link href="/usgaap-ifrs" className="text-sm text-fg-muted hover:underline">
        ← {t("usgaap.all_runs", locale)}
      </Link>
      <div className="rounded-md border border-danger bg-danger/5 p-4 text-sm text-danger">
        <p className="font-medium">{t("usgaap.render_error", locale)}</p>
        <p className="mt-2 whitespace-pre-wrap font-mono text-xs">
          {error.message}
          {error.digest ? `\n\ndigest: ${error.digest}` : ""}
        </p>
        <div className="mt-3 flex gap-2">
          <Button size="sm" onClick={() => reset()}>
            {t("common.retry", locale)}
          </Button>
          <Link href="/usgaap-ifrs">
            <Button size="sm" variant="outline">
              {t("usgaap.back_to_runs", locale)}
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
