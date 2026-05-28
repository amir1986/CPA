import Link from "next/link";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";

import { ApiError, apiFetch } from "@/lib/api/client";
import type { ComparisonRunDetail } from "@/lib/api/types";
import { t, type Locale } from "@/lib/i18n";

import { ExportMemoButton } from "@/components/comparison/ExportMemoButton";
import { FrameworkConfirm } from "@/components/comparison/FrameworkConfirm";
import { IssueCard, type IssueData } from "@/components/comparison/IssueCard";
import { RunStatusPill } from "@/components/comparison/RunStatusPill";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ runId: string }> };

export default async function RunDetail({ params }: Props) {
  const { runId } = await params;
  const cookieStore = await cookies();
  const locale: Locale = cookieStore.get("cpa_locale")?.value === "en" ? "en" : "he";
  const tr = (k: string, v?: Record<string, string | number>) => t(k, locale, v);

  let run: ComparisonRunDetail;
  try {
    run = await apiFetch<ComparisonRunDetail>(`/comparison/runs/${runId}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    const message =
      err instanceof ApiError
        ? `${err.code ?? "api_error"} (${err.status}): ${err.problem.detail || err.message}`
        : (err as Error).message || String(err);
    return (
      <div className="mx-auto max-w-3xl space-y-4" data-testid="run-detail-error">
        <Link href="/usgaap-ifrs" className="text-sm text-fg-muted hover:underline">
          ← {tr("usgaap.all_runs")}
        </Link>
        <div className="rounded-md border border-danger bg-danger/5 p-4 text-sm text-danger">
          <p className="font-medium">{tr("usgaap.could_not_load", { id: runId })}</p>
          <p className="mt-2 whitespace-pre-wrap">{message}</p>
        </div>
      </div>
    );
  }

  const effective: "US" | "IFRS" = (run.override_framework ?? run.detected_framework ?? "US") as
    | "US"
    | "IFRS";

  return (
    <div className="mx-auto max-w-6xl space-y-6" data-testid="run-detail">
      <nav className="text-sm">
        <Link href="/usgaap-ifrs" className="text-fg-muted hover:underline">
          ← {tr("usgaap.all_runs")}
        </Link>
      </nav>

      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{tr("usgaap.title")}</h1>
          <p className="text-sm text-fg-muted">{run.file_names.join(", ") || "—"}</p>
        </div>
        <div className="flex items-center gap-3">
          <RunStatusPill runId={run.id} initial={run.status} />
          {run.status === "done" && run.issues.length > 0 && <ExportMemoButton runId={run.id} />}
        </div>
      </header>

      {run.error && (
        <div
          className="rounded-md border border-danger bg-danger/5 p-3 text-sm text-danger"
          data-testid="run-error"
        >
          {run.error}
        </div>
      )}

      {(run.status === "comparing" || run.status === "done") && (
        <FrameworkConfirm
          runId={run.id}
          detected={run.detected_framework}
          current={run.override_framework}
          confidence={run.confidence}
          rationale={run.rationale}
        />
      )}

      {run.issues.length > 0 ? (
        <div className="space-y-4" data-testid="issues">
          {run.issues.map((i) => (
            <IssueCard key={i.id} issue={i as IssueData} currentFramework={effective} />
          ))}
        </div>
      ) : run.status === "done" ? (
        <p className="rounded-lg border border-dashed border-border bg-bg p-6 text-center text-sm text-fg-muted">
          {tr("usgaap.no_issues_identified")}
        </p>
      ) : null}
    </div>
  );
}
