import { redirect } from "next/navigation";

import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api/client";
import type { CoaAccount } from "@/lib/api/types";

type Props = { params: Promise<{ eid: string }> };

async function importTemplate(formData: FormData) {
  "use server";
  const eid = String(formData.get("eid"));
  const template = String(formData.get("template") ?? "us_gaap");
  await apiFetch(`/engagements/${eid}/coa/import`, { method: "POST", body: { template } });
  redirect(`/engagements/${eid}/books/coa`);
}

export default async function CoaPage({ params }: Props) {
  const { eid } = await params;
  const rows = await apiFetch<CoaAccount[]>(`/engagements/${eid}/coa`);

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-4 flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold">Chart of accounts</h1>
          <p className="mt-1 text-sm text-fg-muted">{rows.length} accounts.</p>
        </div>
        {rows.length === 0 && (
          <form action={importTemplate} className="flex items-center gap-2">
            <input type="hidden" name="eid" value={eid} />
            <select name="template" defaultValue="us_gaap" className="rounded-md border border-border bg-bg-elev px-2 py-1.5 text-sm">
              <option value="us_gaap">US-GAAP template</option>
              <option value="ifrs">IFRS template</option>
            </select>
            <Button type="submit">Import</Button>
          </form>
        )}
      </header>
      <section className="overflow-hidden rounded-lg border border-border bg-bg">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-fg-subtle">
            <tr>
              <th className="px-3 py-2">Code</th>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Currency</th>
              <th className="px-3 py-2">Active</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((a) => (
              <tr key={a.id}>
                <td className="px-3 py-1.5 font-mono">{a.code}</td>
                <td className="px-3 py-1.5">{a.name}</td>
                <td className="px-3 py-1.5">
                  <span className="rounded-pill bg-bg-elev px-2 py-0.5 text-xs">{a.type}</span>
                </td>
                <td className="px-3 py-1.5 text-fg-muted">{a.currency ?? "—"}</td>
                <td className="px-3 py-1.5">{a.active ? "yes" : "no"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && (
          <p className="px-4 py-6 text-sm text-fg-muted">
            No accounts yet — import a template above to bootstrap.
          </p>
        )}
      </section>
    </div>
  );
}
