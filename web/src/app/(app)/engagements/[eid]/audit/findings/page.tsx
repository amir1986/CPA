import { apiFetch } from "@/lib/api/client";
import { t } from "@/lib/i18n";
import { getLocale } from "@/lib/i18n/server";

type Finding = {
  id: string;
  workpaper_id: string | null;
  assertion: string | null;
  risk_level: string;
  description: string;
  evidence_refs: Record<string, unknown>;
};

type Props = { params: Promise<{ eid: string }> };

export default async function FindingsPage({ params }: Props) {
  const locale = await getLocale();
  const tr = (k: string) => t(k, locale);
  const { eid } = await params;
  const rows = await apiFetch<Finding[]>(`/engagements/${eid}/audit/findings`);

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-3 text-xl font-semibold">{tr("audit.findings_title")}</h1>
      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border bg-bg p-6 text-sm text-fg-muted">
          {tr("audit.no_findings")}
        </p>
      ) : (
        <ul className="space-y-2">
          {rows.map((f) => (
            <li key={f.id} className="rounded-lg border border-border bg-bg p-4">
              <div className="mb-1 flex items-center justify-between">
                <span className="rounded-pill bg-bg-elev px-2 py-0.5 text-xs uppercase">{f.risk_level}</span>
                {f.assertion && <span className="text-xs text-fg-muted">{f.assertion}</span>}
              </div>
              <p className="text-sm">{f.description}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
