import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api/client";
import type { QueryOut } from "@/lib/api/types";

type Props = { params: Promise<{ eid: string }>; searchParams: Promise<{ topic?: string }> };

const TOPICS = [
  "Revenue recognition",
  "Leases",
  "Inventory",
  "Intangible assets",
  "Impairment",
  "Financial instruments",
  "Income taxes",
];

export default async function ComparePage({ params, searchParams }: Props) {
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
      <h1 className="mb-1 text-xl font-semibold">GAAP ↔ IFRS comparison</h1>
      <p className="mb-4 text-sm text-fg-muted">
        Picks a topic and runs two parallel /query calls — one US GAAP, one IFRS.
      </p>
      <form className="mb-6 flex flex-wrap items-center gap-2">
        {TOPICS.map((t) => (
          <Button
            key={t}
            variant={topic === t ? "default" : "outline"}
            size="sm"
            type="submit"
            name="topic"
            value={t}
            formMethod="get"
          >
            {t}
          </Button>
        ))}
      </form>

      {topic && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Pane title="US GAAP" data={gaap} />
          <Pane title="IFRS" data={ifrs} />
        </div>
      )}
    </div>
  );
}

function Pane({ title, data }: { title: string; data: QueryOut | null }) {
  return (
    <section className="rounded-lg border border-border bg-bg p-4">
      <h2 className="mb-2 text-sm font-medium">{title}</h2>
      {!data && <p className="text-sm text-fg-muted">No response.</p>}
      {data?.refused && (
        <p className="rounded-md border border-warning bg-warning/5 px-3 py-2 text-sm text-warning">
          Out of corpus for {title}.
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
