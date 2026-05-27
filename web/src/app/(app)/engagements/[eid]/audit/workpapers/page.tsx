import { apiFetch } from "@/lib/api/client";
import { t } from "@/lib/i18n";
import { getLocale } from "@/lib/i18n/server";

type Workpaper = {
  id: string;
  title: string;
  type: string;
  body_md: string;
  pdf_s3_uri: string | null;
  references: Record<string, unknown>;
};

type Props = { params: Promise<{ eid: string }> };

export default async function WorkpapersPage({ params }: Props) {
  const locale = await getLocale();
  const tr = (k: string) => t(k, locale);
  const { eid } = await params;
  const rows = await apiFetch<Workpaper[]>(`/engagements/${eid}/audit/workpapers`);

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-3 text-xl font-semibold">{tr("audit.workpapers_title")}</h1>
      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border bg-bg p-6 text-sm text-fg-muted">
          {tr("audit.no_workpapers")}{" "}
          <code className="font-mono">POST /engagements/{eid}/audit/workpapers</code>
        </p>
      ) : (
        <ul className="space-y-3">
          {rows.map((w) => (
            <li key={w.id} className="rounded-lg border border-border bg-bg p-4">
              <div className="flex items-center justify-between">
                <h2 className="text-base font-medium">{w.title}</h2>
                <span className="rounded-pill bg-bg-elev px-2 py-0.5 text-xs font-mono">{w.type}</span>
              </div>
              <pre className="mt-3 max-h-72 overflow-auto rounded-md border border-border bg-bg-elev p-3 text-xs font-mono whitespace-pre-wrap">
                {w.body_md}
              </pre>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
