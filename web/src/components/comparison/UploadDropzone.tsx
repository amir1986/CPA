"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

const ACCEPTED = ".pdf,.docx,.xlsx,.csv";
const MAX_FILES = 10;

export function UploadDropzone() {
  const router = useRouter();
  const locale = useLocale();
  const tr = (k: string, v?: Record<string, string | number>) => t(k, locale, v);
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(files: FileList) {
    if (!files.length) return;
    if (files.length > MAX_FILES) {
      setError(tr("errors.max_files_per_run", { n: MAX_FILES }));
      return;
    }
    setBusy(true);
    setError(null);
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f, f.name));
    const res = await fetch(`/api/comparison/runs`, {
      method: "POST",
      body: form,
    });
    setBusy(false);
    if (!res.ok) {
      const body = (await res.json().catch(() => ({}))) as { detail?: string };
      setError(body.detail ?? tr("errors.upload_failed_status", { status: res.status }));
      return;
    }
    const json = (await res.json()) as { id: string };
    router.push(`/usgaap-ifrs/${json.id}`);
  }

  return (
    <div
      className="rounded-lg border border-dashed border-border-strong bg-bg p-8 text-center"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        if (e.dataTransfer.files.length) void submit(e.dataTransfer.files);
      }}
    >
      <h2 className="text-base font-medium">{tr("usgaap.drop_zone_title")}</h2>
      <p className="mt-1 text-xs text-fg-muted">{tr("usgaap.drop_zone_hint")}</p>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files?.length) void submit(e.target.files);
        }}
      />
      <div className="mt-5 flex items-center justify-center gap-3">
        <Button onClick={() => inputRef.current?.click()} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          <span>{busy ? tr("usgaap.uploading") : tr("usgaap.choose_files")}</span>
        </Button>
      </div>
      {error && <p className="mt-3 text-sm text-danger">{error}</p>}
    </div>
  );
}
