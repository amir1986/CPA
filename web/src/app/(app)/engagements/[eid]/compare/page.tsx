import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api/client";
import type { QueryOut } from "@/lib/api/types";
import { t } from "@/lib/i18n";
import { getLocale } from "@/lib/i18n/server";

type Props = { params: Promise<{ eid: string }>; searchParams: Promise<{ topic?: string }> };

const TOPICS = [
  ["Revenue recognition", "compare.revenue_recognition"],
  ["Leases", "compare.leases"],
  ["Inventory", "compare.inventory"],
  ["Intangible assets", "compare.intangible_assets"],
  ["Impairment", "compare.impairment"],
  ["Financial instruments", "compare.financial_instruments"],
  ["Income taxes", "compare.income_taxes"],
] as const;

export default async function ComparePage({ params, searchParams }: Props) {
  const locale = await getLocale();
  const tr = (k: string, v?: Record<string, string | number>) => t(k, locale, v);
  await params;
  const sp = await searchParams;
  const topic = sp.topic ?? "";

  const [gaap, ifrs] = topic
    ? await Promise.all([
        apiFetch<QueryOut>("/query", {
          method: "POST",
          body: {
            question: `Summarize the US GAAP treatment of: ${topic}.`,
            jurisdictions: ["US"],
            corpus_types: ["accounting"],
          },
        }).catch(() => null),
        apiFetch<QueryOut>("/query", {
          method: "POST",
          body: {
            question: `Summarize the IFRS treatment of: ${topic}.`,
            jurisdictions: ["IFRS"],
            corpus_types: ["accounting"],
          },
        }).catch(() => null),
      ])
    : [null, null];

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-1 text-xl font-semibold">{tr("compare.title")}</h1>
      <p className="mb-4 text-sm text-fg-muted">{tr("compare.subtitle")}</p>
      <form className="mb-6 flex flex-wrap items-center gap-2">
        {TOPICS.map(([value, labelKey]) => (
          <Button
            key={value}
            variant={topic === value ? "default" : "outline"}
            size="sm"
            type="submit"
            name="topic"
            value={value}
            formMethod="get"
          >
            {tr(labelKey)}
          </Button>
        ))}
      </form>

      {topic && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Pane title="US GAAP" data={gaap} tr={tr} />
          <Pane title="IFRS" data={ifrs} tr={tr} />
        </div>
      )}
    </div>
  );
}

function Pane({ title, data, tr }: { title: string; data: QueryOut | null; tr: (k: string, v?: Record<string, string | number>) => string }) {
  return (
    <section className="rounded-lg border border-border bg-bg p-4">
      <h2 className="mb-2 text-sm font-medium">{title}</h2>
      {!data && <p className="text-sm text-fg-muted">{tr("compare.no_response")}</p>}
      {data?.refused && (
        <p className="rounded-md border border-warning bg-warning/5 px-3 py-2 text-sm text-warning">
          {tr("compare.out_of_corpus", { title })}
        </p>
      )}
      {data && !data.refused && (
        <>
          <p className="whitespace-pre-wrap text-sm">{data.answer}</p>
          <div className="mt-3 flex flex-wrap gap-1">
            {data.citations.map((c, i) => (
              <span key={i} className="rounded-pill border border-border-strong bg-bg-elev px-2 py-0.5 font-mono text-xs">
                {c.standard ?? c.url.replace(/^https?:\/\//, "").slice(0, 28)}
              </span>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
