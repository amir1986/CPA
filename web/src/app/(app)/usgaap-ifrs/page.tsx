import Link from "next/link";

import { apiFetch } from "@/lib/api/client";
import type { ComparisonRunSummary } from "@/lib/api/types";

import { UploadDropzone } from "@/components/comparison/UploadDropzone";

export const dynamic = "force-dynamic";

export default async function UsGaapIfrsPage() {
  let runs: ComparisonRunSummary[] = [];
  try {
    runs = await apiFetch<ComparisonRunSummary[]>("/comparison/runs");
  } catch {
    // Most likely: not signed in. Auth middleware will redirect; render empty.
    runs = [];
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8" data-testid="usgaap-ifrs-page">
      <header>
        <h1 className="text-xl font-semibold">USGAAP &lt;&gt; IFRS</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Upload an accounting policy, contract, financial statements, trial balance
          or GL. The model detects whether the content sits in US GAAP or IFRS,
          identifies the accounting issues inside it, then renders a per-issue
          side-by-side conversion with citations from the standards corpus.
        </p>
      </header>

      <UploadDropzone />

      <section>
        <h2 className="mb-3 text-sm font-medium">Recent runs</h2>
        {runs.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border bg-bg p-6 text-center text-sm text-fg-muted">
            No runs yet — drop a file above to start your first comparison.
          </p>
        ) : (
          <ul className="space-y-2" data-testid="recent-runs">
            {runs.map((r) => (
              <li key={r.id} className="rounded-lg border border-border bg-bg p-3">
                <Link href={`/usgaap-ifrs/${r.id}`} className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {r.file_names.join(", ") || "(no files)"}
                    </p>
                    <p className="text-xs text-fg-muted">
                      {new Date(r.created_at).toLocaleString()} · {r.issue_count} issue
                      {r.issue_count === 1 ? "" : "s"}
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
                      {r.status}
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
