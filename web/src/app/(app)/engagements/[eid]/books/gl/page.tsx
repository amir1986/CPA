import { apiFetch } from "@/lib/api/client";
import type { GLEntry } from "@/lib/api/types";
import { t } from "@/lib/i18n";
import { getLocale } from "@/lib/i18n/server";

type Props = { params: Promise<{ eid: string }> };

export default async function GLPage({ params }: Props) {
  const locale = await getLocale();
  const tr = (k: string, v?: Record<string, string | number>) => t(k, locale, v);
  const { eid } = await params;
  const data = await apiFetch<{ items: GLEntry[]; total: number }>(`/engagements/${eid}/gl?limit=500`);

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-1 text-xl font-semibold">{tr("books.general_ledger")}</h1>
      <p className="mb-4 text-sm text-fg-muted">
        {tr("books.entries_summary", { total: data.total, shown: data.items.length })}
      </p>
      <section className="overflow-hidden rounded-lg border border-border bg-bg">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-fg-subtle">
            <tr>
              <th className="px-3 py-2">{tr("books.je_no")}</th>
              <th className="px-3 py-2">{tr("common.date")}</th>
              <th className="px-3 py-2">{tr("common.description")}</th>
              <th className="px-3 py-2 text-right">{tr("books.debit")}</th>
              <th className="px-3 py-2 text-right">{tr("books.credit")}</th>
              <th className="px-3 py-2">{tr("books.preparer")}</th>
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
          <p className="px-4 py-6 text-sm text-fg-muted">{tr("books.no_gl_entries")}</p>
        )}
      </section>
    </div>
  );
}
