import { redirect } from "next/navigation";

import { Button } from "@/components/ui/button";
import { apiFetch, ApiError } from "@/lib/api/client";
import type { JETestRun } from "@/lib/api/types";
import { t } from "@/lib/i18n";
import { getLocale } from "@/lib/i18n/server";

const TESTS = [
  "benford",
  "weekend_holiday",
  "round_amounts",
  "unusual_user",
  "late_postings",
  "threshold",
] as const;

type Props = { params: Promise<{ eid: string }>; searchParams: Promise<Record<string, string>> };

async function runTest(formData: FormData) {
  "use server";
  const eid = String(formData.get("eid"));
  const test_kind = String(formData.get("test_kind") ?? "benford");
  const amount_threshold = formData.get("amount_threshold");
  const body: Record<string, unknown> = { test_kind };
  if (amount_threshold) body.amount_threshold = Number(amount_threshold);
  try {
    const r = await apiFetch<JETestRun>(`/engagements/${eid}/audit/je-tests`, {
      method: "POST",
      body,
    });
    redirect(`/engagements/${eid}/audit/je-tests?run=${r.id}`);
  } catch (e) {
    if (e instanceof ApiError)
      redirect(`/engagements/${eid}/audit/je-tests?error=${encodeURIComponent(e.problem.detail)}`);
    throw e;
  }
}

export default async function JETestsPage({ params, searchParams }: Props) {
  const locale = await getLocale();
  const tr = (k: string) => t(k, locale);
  const { eid } = await params;
  const sp = await searchParams;
  const error = sp.error;

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-1 text-xl font-semibold">{tr("audit.je_tests_title")}</h1>
      <p className="mb-4 text-sm text-fg-muted">{tr("audit.je_tests_subtitle")}</p>
      <form action={runTest} className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-border bg-bg p-4 md:grid-cols-4">
        <input type="hidden" name="eid" value={eid} />
        <label className="text-sm md:col-span-2">
          <span className="block text-xs text-fg-muted">{tr("audit.test")}</span>
          <select name="test_kind" defaultValue="benford" className="mt-1 w-full rounded-md border border-border bg-bg-elev px-2 py-1.5">
            {TESTS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="text-sm">
          <span className="block text-xs text-fg-muted">{tr("audit.amount_threshold")}</span>
          <input name="amount_threshold" placeholder={tr("audit.threshold_placeholder")} className="mt-1 w-full rounded-md border border-border bg-bg-elev px-2 py-1.5" />
        </label>
        <div className="flex items-end"><Button type="submit">{tr("common.run")}</Button></div>
      </form>
      {error && <p className="mb-3 rounded-md border border-danger bg-danger/5 px-3 py-2 text-sm text-danger">{error}</p>}
      <p className="text-sm text-fg-muted">
        {tr("audit.je_tests_note")}
      </p>
    </div>
  );
}
