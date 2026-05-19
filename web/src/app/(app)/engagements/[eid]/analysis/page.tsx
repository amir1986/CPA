import { apiFetch, ApiError } from "@/lib/api/client";
import type { Ratio, RatioRun } from "@/lib/api/types";

type Benford = {
  observed: Record<string, number>;
  observed_pct: Record<string, number>;
  expected_pct: Record<string, number>;
  chi_square: number;
  n: number;
  suspect: boolean;
};

type Props = { params: Promise<{ eid: string }>; searchParams: Promise<{ period_end?: string }> };

export default async function AnalysisPage({ params, searchParams }: Props) {
  const { eid } = await params;
  const sp = await searchParams;
  const period = sp.period_end ?? new Date().toISOString().slice(0, 10);

  let ratios: RatioRun | null = null;
  let ratioErr: string | null = null;
  try {
    ratios = await apiFetch<RatioRun>(`/engagements/${eid}/analyze/ratios?period_end=${period}`);
  } catch (e) {
    ratioErr = e instanceof ApiError ? e.problem.detail : String(e);
  }

  let benford: Benford | null = null;
  try {
    benford = await apiFetch<Benford>(`/engagements/${eid}/analyze/benford`);
  } catch {
    benford = null;
  }

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-1 text-xl font-semibold">Analysis</h1>
      <p className="mb-4 text-sm text-fg-muted">Ratios + Benford 1st-digit on the GL.</p>

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-medium">Ratios — period_end = {period}</h2>
        {ratioErr && <p className="rounded-md border border-warning bg-warning/5 px-3 py-2 text-sm text-warning">{ratioErr}</p>}
        {ratios && (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {ratios.ratios.map((r) => (
              <RatioCard key={r.name} r={r} />
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-sm font-medium">Benford 1st-digit</h2>
        {!benford && <p className="text-sm text-fg-muted">Run more GL ingestion to populate.</p>}
        {benford && (
          <div className="rounded-lg border border-border bg-bg p-4">
            <div className="mb-3 flex items-center justify-between text-sm">
              <div>
                n = <span className="font-mono">{benford.n}</span> · χ² ={" "}
                <span className="font-mono">{benford.chi_square.toFixed(2)}</span>
              </div>
              <span className={
                "rounded-pill px-2 py-0.5 text-xs " +
                (benford.suspect ? "bg-anomaly/10 text-anomaly" : "bg-success/10 text-success")
              }>
                {benford.suspect ? "anomalous" : "consistent with Benford"}
              </span>
            </div>
            <div className="grid grid-cols-9 gap-2 text-center text-xs">
              {Array.from({ length: 9 }, (_, i) => i + 1).map((d) => {
                const obs = (benford!.observed_pct[String(d)] ?? 0) * 100;
                const exp = (benford!.expected_pct[String(d)] ?? 0) * 100;
                return (
                  <div key={d} className="flex flex-col items-center">
                    <div className="flex h-24 items-end gap-0.5">
                      <div title={`observed ${obs.toFixed(1)}%`} className="w-3 bg-brand" style={{ height: `${obs * 3}px` }} />
                      <div title={`expected ${exp.toFixed(1)}%`} className="w-3 bg-fg-subtle/50" style={{ height: `${exp * 3}px` }} />
                    </div>
                    <span className="mt-1 font-mono">{d}</span>
                  </div>
                );
              })}
            </div>
            <p className="mt-2 text-xs text-fg-muted">Solid = observed · faded = expected.</p>
          </div>
        )}
      </section>
    </div>
  );
}

function RatioCard({ r }: { r: Ratio }) {
  const display = r.value === null ? "—" : r.value.toFixed(3);
  return (
    <div className="rounded-lg border border-border bg-bg p-3">
      <div className="text-xs uppercase tracking-wide text-fg-subtle">{r.name.replaceAll("_", " ")}</div>
      <div className="mt-1 text-2xl font-semibold font-mono">{display}</div>
      <div className="mt-2 text-xs text-fg-muted">
        num={r.numerator.toFixed(0)} · den={r.denominator.toFixed(0)}
      </div>
    </div>
  );
}
