"use client";

import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

import { CiteChip, type ChipCitation } from "./CiteChip";

export type IssueData = {
  id: string;
  seq: number;
  topic: string;
  current_summary: string;
  current_user_cites: { ref: string; anchor: string; quote: string }[];
  gaap_summary: string | null;
  gaap_citations: ChipCitation[];
  ifrs_summary: string | null;
  ifrs_citations: ChipCitation[];
  differences: string | null;
  conversion_impact: string | null;
  gaap_verification: string | null;
  ifrs_verification: string | null;
};

export function IssueCard({ issue, currentFramework }: { issue: IssueData; currentFramework: "US" | "IFRS" }) {
  const locale = useLocale();
  const tr = (k: string, v?: Record<string, string | number>) => t(k, locale, v);
  const isUS = currentFramework === "US";
  const currentCites = isUS ? issue.gaap_citations : issue.ifrs_citations;
  const otherCites = isUS ? issue.ifrs_citations : issue.gaap_citations;
  const currentStandardsSummary = isUS ? issue.gaap_summary : issue.ifrs_summary;
  const otherStandardsSummary = isUS ? issue.ifrs_summary : issue.gaap_summary;
  const currentVerif = isUS ? issue.gaap_verification : issue.ifrs_verification;
  const otherVerif = isUS ? issue.ifrs_verification : issue.gaap_verification;
  const fwLabel = (fw: "US" | "IFRS") => (fw === "US" ? tr("usgaap.us_gaap") : tr("usgaap.ifrs"));
  const currentLabel = tr("usgaap.current_treatment", { fw: fwLabel(currentFramework) });
  const otherLabel = tr("usgaap.converted_to", { fw: fwLabel(isUS ? "IFRS" : "US") });

  return (
    <article
      className="rounded-lg border border-border bg-bg p-5"
      data-testid="issue-card"
      data-topic={issue.topic}
    >
      <header className="mb-3 flex items-center justify-between">
        <h3 className="text-base font-semibold">
          <span className="me-2 text-fg-muted">#{issue.seq}</span>
          {issue.topic}
        </h3>
      </header>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Pane
          label={currentLabel}
          tone="current"
          standardsSummary={currentStandardsSummary}
          standardsCites={currentCites}
          userCites={issue.current_user_cites}
          policySummary={issue.current_summary}
          verification={currentVerif}
          locale={locale}
        />
        <Pane
          label={otherLabel}
          tone="other"
          standardsSummary={otherStandardsSummary}
          standardsCites={otherCites}
          verification={otherVerif}
          locale={locale}
        />
      </div>

      {(issue.differences || issue.conversion_impact) && (
        <footer className="mt-4 rounded-md border border-border bg-bg-elev p-3 text-sm">
          {issue.differences && (
            <p>
              <span className="font-medium">{tr("usgaap.key_differences")}</span>{" "}
              {issue.differences}
            </p>
          )}
          {issue.conversion_impact && (
            <p className="mt-1">
              <span className="font-medium">{tr("usgaap.conversion_impact")}</span>{" "}
              {issue.conversion_impact}
            </p>
          )}
        </footer>
      )}
    </article>
  );
}

function Pane({
  label,
  tone,
  standardsSummary,
  standardsCites,
  userCites,
  policySummary,
  verification,
  locale,
}: {
  label: string;
  tone: "current" | "other";
  standardsSummary: string | null;
  standardsCites: ChipCitation[];
  userCites?: { ref: string; anchor: string; quote: string }[];
  policySummary?: string;
  verification?: string | null;
  locale: "en" | "he";
}) {
  const tr = (k: string) => t(k, locale);
  return (
    <section
      className={
        "rounded-md border p-3 " +
        (tone === "current"
          ? "border-brand/40 bg-brand/5"
          : "border-border bg-bg")
      }
      data-testid={tone === "current" ? "pane-current" : "pane-other"}
    >
      <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-subtle">{label}</h4>

      {policySummary && (
        <div className="mb-3">
          <p className="text-xs uppercase text-fg-subtle">{tr("usgaap.from_your_document")}</p>
          <p className="mt-1 whitespace-pre-wrap text-sm">{policySummary}</p>
          {userCites && userCites.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-fg-muted">
              {userCites.map((c, i) => (
                <li key={i} className="rounded-md bg-bg-elev p-2">
                  <span className="font-mono">{c.anchor}</span>
                  {c.quote && <span> — {c.quote.slice(0, 240)}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <p className="text-xs uppercase text-fg-subtle">{tr("usgaap.from_standards")}</p>
      <p className="mt-1 whitespace-pre-wrap text-sm">
        {standardsSummary ?? <span className="text-fg-muted">{tr("usgaap.no_standards_retrieved")}</span>}
      </p>

      {/* Verbatim cited paragraphs from the standards, shown inline beneath
          the summary so the source is right next to the implementation. */}
      {standardsCites.length > 0 && (
        <div className="mt-3 space-y-2">
          <p className="text-xs uppercase text-fg-subtle">{tr("usgaap.source_paragraphs_verbatim")}</p>
          {standardsCites.map((c, i) => (
            <blockquote
              key={i}
              className="rounded-md border-s-2 border-border-strong bg-bg-elev px-3 py-2 text-xs"
            >
              <div className="mb-1 flex items-center justify-between gap-2">
                <CiteChip citation={c} />
              </div>
              {c.quote && (
                <p className="whitespace-pre-wrap italic text-fg">&ldquo;{c.quote}&rdquo;</p>
              )}
            </blockquote>
          ))}
        </div>
      )}

      {verification && (
        <div
          className="mt-3 rounded-md border border-warning/40 bg-warning/5 p-2 text-xs"
          data-testid="verifier-report"
        >
          <p className="mb-1 font-medium text-warning">{tr("usgaap.verifier_agent")}</p>
          <p className="whitespace-pre-wrap text-fg">{verification}</p>
        </div>
      )}
    </section>
  );
}
