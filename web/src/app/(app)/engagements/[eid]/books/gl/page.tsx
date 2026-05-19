import { apiFetch } from "@/lib/api/client";
import type { GLEntry } from "@/lib/api/types";

type Props = { params: Promise<{ eid: string }> };

export default async function GLPage({ params }: Props) {
  const { eid } = await params;
  const data = await apiFetch<{ items: GLEntry[]; total: number }>(`/engagements/${eid}/gl?limit=500`);

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-1 text-xl font-semibold">General ledger</h1>
      <p className="mb-4 text-sm text-fg-muted">{data.total} entries (showing first {data.items.length})</p>
      <section className="overflow-hidden rounded-lg border border-border bg-bg">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-fg-subtle">
            <tr>
              <th className="px-3 py-2">JE No</th>
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2">Description</th>
              <th className="px-3 py-2 text-right">Debit</th>
              <th className="px-3 py-2 text-right">Credit</th>
              <th className="px-3 py-2">Preparer</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data.items.map((e) => (
              <tr key={e.id}>
                <td className="px-3 py-1.5 font-mono">{e.je_number ?? "—"}</td>
                <td className="px-3 py-1.5">{e.je_date ?? "—"}</td>
                <td className="px-3 py-1.5">{e.description ?? "—"}</td>
                <td className="px-3 py-1.5 text-right font-mono">{e.debit ? e.debit.toFixed(2) : ""}</td>
                <td className="px-3 py-1.5 text-right font-mono">{e.credit ? e.credit.toFixed(2) : ""}</td>
                <td className="px-3 py-1.5 text-fg-muted">{e.preparer ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.items.length === 0 && (
          <p className="px-4 py-6 text-sm text-fg-muted">No GL entries yet. Upload a GL file under Documents.</p>
        )}
      </section>
    </div>
  );
}
