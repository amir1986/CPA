"use client";

import { useRef, useState } from "react";
import { Loader2, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

const KINDS = ["trial_balance", "gl", "bank", "invoice", "financial_statements", "contract", "policy", "other"] as const;

export function UploadForm({ engagementId }: { engagementId: string }) {
  const locale = useLocale();
  const [kind, setKind] = useState<(typeof KINDS)[number]>("trial_balance");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function submit(file: File) {
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("kind", kind);
    const res = await fetch(`/api/engagements/${engagementId}/files`, {
      method: "POST",
      body: form,
    });
    setBusy(false);
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      setError(body.detail ?? t("documents.upload_failed", locale));
      return;
    }
    // Reload server-side data.
    window.location.reload();
  }

  return (
    <div
      className="rounded-lg border border-dashed border-border-strong bg-bg p-6"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        const f = e.dataTransfer.files[0];
        if (f) void submit(f);
      }}
    >
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="text-sm font-medium">{t("documents.drop_title", locale)}</h3>
          <p className="mt-1 text-xs text-fg-muted">
            {t("documents.drop_hint", locale)} <code className="font-mono">{kind}</code>.
          </p>
        </div>
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as (typeof KINDS)[number])}
          className="rounded-md border border-border bg-bg-elev px-2 py-1.5 text-sm"
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>{k}</option>
          ))}
        </select>
      </div>
      <div className="mt-4 flex items-center gap-3">
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void submit(f);
          }}
        />
        <Button onClick={() => inputRef.current?.click()} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          {busy ? t("documents.uploading", locale) : t("documents.choose_file", locale)}
        </Button>
        {error && <span className="text-sm text-danger">{error}</span>}
      </div>
    </div>
  );
}
