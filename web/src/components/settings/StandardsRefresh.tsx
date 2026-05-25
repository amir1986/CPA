"use client";

import { useEffect, useState, useTransition } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

type IngestRun = {
  id: string;
  source_id: string;
  status: "running" | "done" | "failed";
  chunks_count: number | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export function StandardsRefresh() {
  const locale = useLocale();
  const tr = (k: string, v?: Record<string, string | number>) => t(k, locale, v);
  const [runs, setRuns] = useState<IngestRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  // Initial load + 5s poll while any run is in 'running' state so the UI
  // reflects the orchestrator progress without a manual refresh.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function load() {
      try {
        const res = await fetch("/api/admin/standards/runs");
        if (cancelled) return;
        if (!res.ok) {
          setError(`load failed (${res.status})`);
          return;
        }
        const data = (await res.json()) as IngestRun[];
        setRuns(data);
        // Schedule next poll only if something is still running.
        if (!cancelled && data.some((r) => r.status === "running")) {
          timer = setTimeout(load, 5000);
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    }

    void load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  function refresh() {
    setError(null);
    startTransition(async () => {
      const res = await fetch("/api/admin/standards/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: string };
        setError(body.detail ?? `refresh failed (${res.status})`);
        return;
      }
      // Re-poll the runs list so the new 'running' rows appear immediately.
      const listed = await fetch("/api/admin/standards/runs");
      if (listed.ok) setRuns((await listed.json()) as IngestRun[]);
    });
  }

  return (
    <div className="space-y-3" data-testid="standards-refresh">
      <div>
        <h3 className="text-sm font-medium">{tr("settings.standards_title")}</h3>
        <p className="mt-1 text-xs text-fg-muted">{tr("settings.standards_hint")}</p>
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={refresh} disabled={pending}>
          {pending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          {pending ? tr("settings.refreshing") : tr("settings.refresh_standards")}
        </Button>
        {error && <span className="text-sm text-danger">{error}</span>}
      </div>
      {runs && runs.length === 0 && (
        <p className="rounded-md border border-dashed border-border bg-bg-elev p-3 text-xs text-fg-muted">
          {tr("settings.no_runs")}
        </p>
      )}
      {runs && runs.length > 0 && (
        <ul className="space-y-1" data-testid="standards-runs">
          {runs.slice(0, 10).map((r) => (
            <li
              key={r.id}
              className="flex items-center justify-between gap-3 rounded-md border border-border bg-bg-elev px-3 py-2 text-xs"
            >
              <div className="min-w-0">
                <p className="truncate font-mono">{r.source_id}</p>
                <p className="text-fg-muted">
                  {new Date(r.started_at).toLocaleString(locale)}
                  {r.chunks_count != null
                    ? " · " + tr("settings.chunks", { n: r.chunks_count })
                    : ""}
                </p>
                {r.error && <p className="mt-1 text-danger">{r.error}</p>}
              </div>
              <span
                className={
                  "rounded-pill border px-2 py-0.5 text-xs " +
                  (r.status === "done"
                    ? "border-success bg-success/10 text-success"
                    : r.status === "failed"
                    ? "border-danger bg-danger/10 text-danger"
                    : "border-info bg-info/10 text-info")
                }
              >
                {tr(`settings.status_${r.status}`)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
