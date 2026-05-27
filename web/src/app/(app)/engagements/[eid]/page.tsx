import Link from "next/link";

import { apiFetch } from "@/lib/api/client";
import type { AgentRun, Engagement, FileOut } from "@/lib/api/types";
import { t } from "@/lib/i18n";
import { getLocale } from "@/lib/i18n/server";

type Props = { params: Promise<{ eid: string }> };

export default async function EngagementDashboard({ params }: Props) {
  const locale = await getLocale();
  const tr = (k: string, v?: Record<string, string | number>) => t(k, locale, v);
  const { eid } = await params;
  const [eng, files, runs] = await Promise.all([
    apiFetch<Engagement>(`/engagements/${eid}`),
    apiFetch<{ items: FileOut[]; total: number }>(`/engagements/${eid}/files`),
    apiFetch<AgentRun[]>(`/engagements/${eid}/agent/runs?limit=5`).catch(() => []),
  ]);

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-6">
        <div className="flex items-baseline justify-between">
          <h1 className="text-2xl font-semibold">{eng.name}</h1>
          <span className="rounded-pill border border-border-strong bg-bg-elev px-2 py-0.5 text-xs uppercase">
            {eng.status}
          </span>
        </div>
        <p className="mt-1 text-sm text-fg-muted">
          {eng.type} · {eng.period_start ?? "—"} → {eng.period_end ?? "—"}
        </p>
      </header>

      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Kpi label={tr("engagements.materiality")} value={eng.materiality?.toLocaleString() ?? "—"} />
        <Kpi label={tr("engagements.performance_materiality")} value={eng.performance_materiality?.toLocaleString() ?? "—"} />
        <Kpi label={tr("engagements.files_uploaded")} value={files.total.toString()} />
      </section>

      <section className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-3">
        <QuickAction href={`/engagements/${eid}/chat`} title={tr("engagements.ask_question")} desc={tr("engagements.ask_question_desc")} />
        <QuickAction href={`/engagements/${eid}/documents`} title={tr("engagements.upload_docs")} desc={tr("engagements.upload_docs_desc")} />
        <QuickAction href={`/engagements/${eid}/audit/samples`} title={tr("engagements.draw_sample")} desc={tr("engagements.draw_sample_desc")} />
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card title={tr("engagements.recent_files")}>
          {files.items.length === 0 ? (
            <Empty msg={tr("engagements.no_files")} />
          ) : (
            <ul className="divide-y divide-border">
              {files.items.slice(0, 6).map((f) => (
                <li key={f.id} className="flex items-center justify-between py-2">
                  <div className="text-sm">{f.original_name}</div>
                  <span className="text-xs text-fg-muted">{f.parsed_status}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title={tr("engagements.recent_agent_runs")}>
          {runs.length === 0 ? (
            <Empty msg={tr("engagements.no_agent_runs")} />
          ) : (
            <ul className="divide-y divide-border">
              {runs.map((r) => (
                <li key={r.id} className="py-2">
                  <Link href={`/engagements/${eid}/traces/${r.id}`} className="block text-sm hover:underline">
                    {r.request.slice(0, 80)}
                  </Link>
                  <div className="text-xs text-fg-muted">
                    {tr(r.tool_calls.length === 1 ? "common.tool_call_count_one" : "common.tool_call_count_many", {
                      n: r.tool_calls.length,
                    })}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </section>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-bg p-4">
      <div className="text-xs uppercase tracking-wide text-fg-subtle">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}

function QuickAction({ href, title, desc }: { href: string; title: string; desc: string }) {
  return (
    <Link
      href={href}
      className="block rounded-lg border border-border bg-bg p-4 transition-colors hover:bg-bg-elev"
    >
      <div className="text-sm font-medium">{title}</div>
      <div className="mt-1 text-xs text-fg-muted">{desc}</div>
    </Link>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-bg p-4">
      <h2 className="mb-2 text-sm font-medium">{title}</h2>
      {children}
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return <p className="py-4 text-sm text-fg-muted">{msg}</p>;
}
