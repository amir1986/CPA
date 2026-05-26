import Link from "next/link";

import { apiFetch } from "@/lib/api/client";
import type { AgentRun } from "@/lib/api/types";
import { t } from "@/lib/i18n";
import { getLocale } from "@/lib/i18n/server";

type Props = { params: Promise<{ eid: string }> };

export default async function TracesPage({ params }: Props) {
  const locale = await getLocale();
  const tr = (k: string, v?: Record<string, string | number>) => t(k, locale, v);
  const { eid } = await params;
  const rows = await apiFetch<AgentRun[]>(`/engagements/${eid}/agent/runs?limit=50`);

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-3 text-xl font-semibold">{tr("traces.title")}</h1>
      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border bg-bg p-6 text-sm text-fg-muted">
          {tr("traces.no_runs")}{" "}
          <code className="font-mono">POST /engagements/{eid}/agent</code>.
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-bg">
          {rows.map((r) => (
            <li key={r.id}>
              <Link href={`/engagements/${eid}/traces/${r.id}`} className="block px-4 py-3 hover:bg-bg-elev">
                <div className="text-sm font-medium">{r.request.slice(0, 100)}</div>
                <div className="mt-1 text-xs text-fg-muted">
                  {tr(r.tool_calls.length === 1 ? "common.tool_call_count_one" : "common.tool_call_count_many", {
                    n: r.tool_calls.length,
                  })} ·{" "}
                  {new Date(r.created_at).toLocaleString()}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
