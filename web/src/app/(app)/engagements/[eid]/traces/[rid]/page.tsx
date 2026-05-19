import { apiFetch } from "@/lib/api/client";
import type { AgentRun } from "@/lib/api/types";

type Props = { params: Promise<{ eid: string; rid: string }> };

export default async function TraceDetailPage({ params }: Props) {
  const { eid, rid } = await params;
  const run = await apiFetch<AgentRun>(`/engagements/${eid}/agent/runs/${rid}`);

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-1 text-xl font-semibold">Trace</h1>
      <p className="mb-4 text-sm text-fg-muted">{new Date(run.created_at).toLocaleString()}</p>

      <section className="mb-4 rounded-lg border border-border bg-bg p-4">
        <h2 className="mb-1 text-sm font-medium">Question</h2>
        <p className="text-sm">{run.request}</p>
      </section>

      <h2 className="mb-2 text-sm font-medium">Tool calls</h2>
      <ol className="space-y-2">
        {run.tool_calls.map((tc, i) => (
          <li key={i} className="rounded-lg border border-border bg-bg p-3">
            <div className="flex items-center justify-between">
              <code className="font-mono text-sm">{i + 1}. {tc.tool}</code>
              {tc.error && <span className="rounded-pill bg-danger/10 px-2 py-0.5 text-xs text-danger">error</span>}
            </div>
            <pre className="mt-2 max-h-60 overflow-auto rounded-md bg-bg-elev p-2 text-xs">
{JSON.stringify({ arguments: tc.arguments, result: tc.result, error: tc.error }, null, 2)}
            </pre>
          </li>
        ))}
      </ol>

      <h2 className="mt-6 mb-2 text-sm font-medium">Final answer</h2>
      <p className="rounded-lg border border-border bg-bg p-4 text-sm whitespace-pre-wrap">
        {run.final_answer ?? "(no final answer)"}
      </p>
    </div>
  );
}
