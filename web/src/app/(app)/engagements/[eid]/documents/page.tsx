import { apiFetch } from "@/lib/api/client";
import type { FileOut } from "@/lib/api/types";
import { UploadForm } from "@/components/docs/upload-form";
import { t } from "@/lib/i18n";
import { getLocale } from "@/lib/i18n/server";

type Props = { params: Promise<{ eid: string }> };

export default async function DocumentsPage({ params }: Props) {
  const locale = await getLocale();
  const tr = (k: string, v?: Record<string, string | number>) => t(k, locale, v);
  const { eid } = await params;
  const data = await apiFetch<{ items: FileOut[]; total: number }>(`/engagements/${eid}/files`);

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-3 text-xl font-semibold">{tr("documents.title")}</h1>
      <p className="mb-5 text-sm text-fg-muted">
        {tr("documents.subtitle")}
      </p>
      <div className="mb-6">
        <UploadForm engagementId={eid} />
      </div>
      <section className="rounded-lg border border-border bg-bg">
        <header className="border-b border-border px-4 py-2.5 text-xs uppercase text-fg-subtle">
          {tr(data.total === 1 ? "documents.file_count_one" : "documents.file_count_many", { n: data.total })}
        </header>
        {data.items.length === 0 ? (
          <p className="px-4 py-6 text-sm text-fg-muted">{tr("engagements.no_files")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-fg-subtle">
              <tr>
                <th className="px-4 py-2">{tr("common.name")}</th>
                <th className="px-4 py-2">{tr("documents.kind")}</th>
                <th className="px-4 py-2">{tr("common.size")}</th>
                <th className="px-4 py-2">{tr("common.status")}</th>
                <th className="px-4 py-2">{tr("documents.sha256")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.items.map((f) => (
                <tr key={f.id}>
                  <td className="px-4 py-2">{f.original_name}</td>
                  <td className="px-4 py-2 text-fg-muted">{f.kind}</td>
                  <td className="px-4 py-2 text-fg-muted">{(f.size / 1024).toFixed(1)} KB</td>
                  <td className="px-4 py-2">
                    <span className={
                      "rounded-pill px-2 py-0.5 text-xs " +
                      (f.parsed_status === "done"
                        ? "bg-success/10 text-success"
                        : f.parsed_status === "failed"
                          ? "bg-danger/10 text-danger"
                          : "bg-warning/10 text-warning")
                    }>
                      {f.parsed_status}
                    </span>
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-fg-subtle">{f.sha256.slice(0, 12)}…</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
