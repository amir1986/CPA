import { apiFetch } from "@/lib/api/client";
import type { Source } from "@/lib/api/types";

export default async function SourcesPage() {
  const sources = await apiFetch<Source[]>("/sources");

  const grouped = sources.reduce<Record<string, Source[]>>((acc, s) => {
    const key = `${s.corpus_type} · ${s.jurisdiction}`;
    (acc[key] ??= []).push(s);
    return acc;
  }, {});

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="mb-1 text-xl font-semibold">Knowledge sources</h1>
      <p className="mb-4 text-sm text-fg-muted">
        Public-excerpt standards corpora. Full FASB ASC / IFRS Standards text is paywalled; supply
        licensed copies via authenticated upload.
      </p>
      <div className="space-y-5">
        {Object.entries(grouped).map(([k, list]) => (
          <section key={k}>
            <h2 className="mb-2 text-xs uppercase tracking-wide text-fg-subtle">{k}</h2>
            <ul className="divide-y divide-border rounded-lg border border-border bg-bg">
              {list.map((s) => (
                <li key={s.id} className="px-4 py-3">
                  <div className="flex items-baseline justify-between">
                    <span className="text-sm font-medium">{s.name}</span>
                    <span className="rounded-pill bg-bg-elev px-2 py-0.5 text-xs font-mono">{s.language}</span>
                  </div>
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 block text-xs text-brand hover:underline"
                  >
                    {s.url}
                  </a>
                  <p className="mt-1 text-xs text-fg-muted">{s.licence}</p>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
