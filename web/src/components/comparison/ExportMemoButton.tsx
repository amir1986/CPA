"use client";

import { useState } from "react";
import { Download, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

export function ExportMemoButton({ runId }: { runId: string }) {
  const locale = useLocale();
  const tr = (k: string, v?: Record<string, string | number>) => t(k, locale, v);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function download(format: "md" | "pdf") {
    setBusy(true);
    setError(null);
    // Send the current UI locale so the api translates section headings
    // + LLM-generated prose to Hebrew when the user has selected he.
    // Verbatim source quotes stay in their original language regardless.
    const res = await fetch(`/api/comparison/runs/${runId}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format, locale }),
    });
    setBusy(false);
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      setError(body.detail ?? tr("errors.export_failed_status", { status: res.status }));
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
        {tr("usgaap.export_to_memo")}
      </Button>
      <Button variant="outline" onClick={() => download("pdf")} disabled={busy}>
        {tr("usgaap.pdf")}
      </Button>
      {error && <span className="text-sm text-danger">{error}</span>}
    </div>
  );
}
