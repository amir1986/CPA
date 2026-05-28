import Link from "next/link";
import { cookies } from "next/headers";

import { apiFetch } from "@/lib/api/client";
import type { ComparisonRunSummary } from "@/lib/api/types";
import { t, type Locale } from "@/lib/i18n";

import { UploadDropzone } from "@/components/comparison/UploadDropzone";

export const dynamic = "force-dynamic";

export default async function UsGaapIfrsPage() {
  const cookieStore = await cookies();
  const locale: Locale = cookieStore.get("cpa_locale")?.value === "en" ? "en" : "he";
  const tr = (k: string, v: Record<string, string | number> = {}) => t(k, locale, v);

  let runs: ComparisonRunSummary[] = [];
  try {
    runs = await apiFetch<ComparisonRunSummary[]>("/comparison/runs");
  } catch {
    runs = [];
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8" data-testid="usgaap-ifrs-page">
      <header>
        <h1 className="text-xl font-semibold">{tr("usgaap.title")}</h1>
        <p className="mt-1 text-sm text-fg-muted">{tr("usgaap.landing_intro")}</p>
      </header>

      <UploadDropzone />

      <section>
        <h2 className="mb-3 text-sm font-medium">{tr("usgaap.recent_runs")}</h2>
        {runs.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border bg-bg p-6 text-center text-sm text-fg-muted">
            {tr("usgaap.no_runs_yet")}
          </p>
        ) : (
          <ul className="space-y-2" data-testid="recent-runs">
            {runs.map((r) => (
              <li key={r.id} className="rounded-lg border border-border bg-bg p-3">
                <Link href={`/usgaap-ifrs/${r.id}`} className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {r.file_names.join(", ") || "—"}
                    </p>
                    <p className="text-xs text-fg-muted">
                      {new Date(r.created_at).toLocaleString(locale)} ·{" "}
                      {r.issue_count === 1
                        ? tr("usgaap.issue_count_one", { n: r.issue_count })
                        : tr("usgaap.issue_count_many", { n: r.issue_count })}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {r.override_framework || r.detected_framework ? (
                      <span className="rounded-pill border border-border-strong bg-bg-elev px-2 py-0.5 font-mono text-xs">
                        {r.override_framework ?? r.detected_framework}
                      </span>
                    ) : null}
                    <span
                      className={
                        "rounded-pill border px-2 py-0.5 text-xs " +
                        (r.status === "done"
                          ? "border-success bg-success/10 text-success"
                          : r.status === "failed"
                          ? "border-danger bg-danger/10 text-danger"
                          : "border-info bg-info/10 text-info")
                      }
                    >
                      {tr(`usgaap.status_${r.status}`)}
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
