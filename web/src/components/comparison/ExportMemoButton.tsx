"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

export function ExportMemoButton({ runId }: { runId: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function download(format: "md" | "pdf") {
    setBusy(true);
    setError(null);
    const res = await fetch(`/api/comparison/runs/${runId}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format }),
    });
    setBusy(false);
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      setError(body.detail ?? `export failed (${res.status})`);
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `usgaap-ifrs-comparison-${runId}.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex items-center gap-2" data-testid="export-controls">
      <Button onClick={() => download("md")} disabled={busy} data-testid="export-md">
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
        Export to memo
      </Button>
      <Button variant="outline" onClick={() => download("pdf")} disabled={busy}>
        PDF
      </Button>
      {error && <span className="text-sm text-danger">{error}</span>}
    </div>
  );
}
