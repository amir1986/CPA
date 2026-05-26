"use client";

import { useState } from "react";

import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

export type ChipCitation = {
  standard?: string | null;
  paragraph?: string | null;
  url: string;
  quote: string;
};

export function CiteChip({ citation }: { citation: ChipCitation }) {
  const [open, setOpen] = useState(false);
  const label = citation.standard
    ? `[${citation.standard}${citation.paragraph ? ` ¶${citation.paragraph}` : ""}]`
    : citation.url.replace(/^https?:\/\//, "").slice(0, 28);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-pill border border-border-strong bg-bg-elev px-2 py-0.5 font-mono text-xs hover:bg-brand/10"
      >
        {label}
      </button>
      {open && <CiteDrawer citation={citation} onClose={() => setOpen(false)} />}
    </>
  );
}

function CiteDrawer({ citation, onClose }: { citation: ChipCitation; onClose: () => void }) {
  const locale = useLocale();
  return (
    <div className="fixed inset-0 z-40 flex items-stretch bg-bg-overlay" onClick={onClose}>
      <div
        className="ms-auto h-full w-full max-w-md overflow-y-auto border-s border-border bg-bg p-5 shadow-e4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">{t("citations.title", locale)}</h2>
          <button onClick={onClose} className="text-fg-muted hover:text-fg">
            ×
          </button>
        </div>
        <dl className="space-y-3 text-sm">
          {citation.standard && (
            <div>
              <dt className="text-xs uppercase text-fg-subtle">{t("citations.standard", locale)}</dt>
              <dd className="font-mono">{citation.standard}</dd>
            </div>
          )}
          {citation.paragraph && (
            <div>
              <dt className="text-xs uppercase text-fg-subtle">{t("citations.paragraph", locale)}</dt>
              <dd className="font-mono">{citation.paragraph}</dd>
            </div>
          )}
          {citation.url && (
            <div>
              <dt className="text-xs uppercase text-fg-subtle">{t("citations.url", locale)}</dt>
              <dd>
                <a href={citation.url} target="_blank" rel="noreferrer" className="text-brand underline">
                  {citation.url}
                </a>
              </dd>
            </div>
          )}
          <div>
            <dt className="text-xs uppercase text-fg-subtle">{t("citations.quote", locale)}</dt>
            <dd className="rounded-md bg-bg-elev p-3 text-sm">{citation.quote}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
