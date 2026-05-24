"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const TERMINAL = new Set(["done", "failed"]);

const LABELS: Record<string, string> = {
  parsing: "Parsing files…",
  detecting: "Detecting framework…",
  comparing: "Comparing standards…",
  done: "Done",
  failed: "Failed",
};

const TONES: Record<string, string> = {
  parsing: "border-info bg-info/10 text-info",
  detecting: "border-info bg-info/10 text-info",
  comparing: "border-info bg-info/10 text-info",
  done: "border-success bg-success/10 text-success",
  failed: "border-danger bg-danger/10 text-danger",
};

export function RunStatusPill({ runId, initial }: { runId: string; initial: string }) {
  const router = useRouter();
  const [status, setStatus] = useState(initial);

  useEffect(() => {
    if (TERMINAL.has(status)) return;
    let aborted = false;
    const controller = new AbortController();
    (async () => {
      try {
        const res = await fetch(`/api/comparison/runs/${runId}/stream`, {
          signal: controller.signal,
          headers: { Accept: "text/event-stream" },
        });
        if (!res.body) return;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        while (!aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buf.indexOf("\n\n")) >= 0) {
            const block = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            let event = "message";
            let data = "";
            for (const line of block.split("\n")) {
              if (line.startsWith("event:")) event = line.slice(6).trim();
              else if (line.startsWith("data:")) data += line.slice(5).trim();
            }
            if (!data) continue;
            try {
              const json = JSON.parse(data) as { status?: string };
              if (event === "status" && json.status) {
                setStatus(json.status);
                if (TERMINAL.has(json.status)) {
                  router.refresh();
                }
              }
            } catch {
              /* ignore */
            }
          }
        }
      } catch {
        /* aborted */
      }
    })();
    return () => {
      aborted = true;
      controller.abort();
    };
  }, [runId, status, router]);

  const tone = TONES[status] ?? "border-border bg-bg-elev";
  return (
    <span
      data-testid="run-status"
      data-status={status}
      className={`inline-flex items-center gap-2 rounded-pill border px-3 py-1 text-xs font-medium ${tone}`}
    >
      {!TERMINAL.has(status) && (
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-current" />
      )}
      {LABELS[status] ?? status}
    </span>
  );
}
