import { apiFetch, ApiError } from "@/lib/api/client";
import type { TrialBalanceRow } from "@/lib/api/types";

type Props = { params: Promise<{ eid: string }>; searchParams: Promise<{ period_end?: string }> };

export default async function TrialBalancePage({ params, searchParams }: Props) {
  const { eid } = await params;
  const sp = await searchParams;
  const period = sp.period_end ?? new Date().toISOString().slice(0, 10);
  let rows: TrialBalanceRow[] = [];
  let err: string | null = null;
  try {
    rows = await apiFetch<TrialBalanceRow[]>(`/engagements/${eid}/trial-balance?period_end=${period}`);
  } catch (e) {
    err = e instanceof ApiError ? e.problem.detail : String(e);
  }
  const total = rows.reduce((s, r) => s + (r.closing ?? 0), 0);

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-4 flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold">Trial balance</h1>
          <p className="mt-1 text-sm text-fg-muted">period_end = {period}</p>
        </div>
        <form className="flex items-center gap-2 text-sm">
          <label htmlFor="period_end" className="text-fg-muted">period_end</label>
          <input
            id="period_end"
            name="period_end"
            type="date"
            defaultValue={period}
            className="rounded-md border border-border bg-bg-elev px-2 py-1"
          />
          <button type="submit" className="rounded-md border border-border-strong bg-bg-elev px-3 py-1">
            Load
          </button>
        </form>
      </header>
      {err && <p className="mb-4 rounded-md border border-danger bg-danger/5 px-3 py-2 text-sm text-danger">{err}</p>}
      <section className="overflow-hidden rounded-lg border border-border bg-bg">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-fg-subtle">
            <tr>
              <th className="px-3 py-2">Code</th>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2 text-right">Opening</th>
              <th className="px-3 py-2 text-right">Debit</th>
              <th className="px-3 py-2 text-right">Credit</th>
              <th className="px-3 py-2 text-right">Closing</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border font-mono">
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="px-3 py-1.5">{r.account_code}</td>
                <td className="px-3 py-1.5">{r.account_name}</td>
                <td className="px-3 py-1.5 text-right">{fmt(r.opening)}</td>
                <td className="px-3 py-1.5 text-right">{fmt(r.debit_total)}</td>
                <td className="px-3 py-1.5 text-right">{fmt(r.credit_total)}</td>
                <td className="px-3 py-1.5 text-right">{fmt(r.closing)}</td>
              </tr>
            ))}
          </tbody>
          {rows.length > 0 && (
            <tfoot>
              <tr className="border-t border-border-strong bg-bg-elev font-mono text-sm">
                <td className="px-3 py-2" colSpan={5}>Total</td>
                <td className="px-3 py-2 text-right">{fmt(total)}</td>
              </tr>
            </tfoot>
          )}
        </table>
        {rows.length === 0 && !err && <p className="px-4 py-6 text-sm text-fg-muted">No TB rows for this period.</p>}
      </section>
    </div>
  );
}

function fmt(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
