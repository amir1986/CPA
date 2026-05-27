import { redirect } from "next/navigation";

import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api/client";
import type { Tweaks } from "@/lib/api/types";
import { t } from "@/lib/i18n";
import { getLocale } from "@/lib/i18n/server";

async function patchTweaks(formData: FormData) {
  "use server";
  const top_k_raw = formData.get("top_k");
  const min_score_raw = formData.get("min_score");
  const lang_strict_raw = formData.get("lang_strict");
  const payload: Record<string, unknown> = {};
  if (top_k_raw && top_k_raw !== "") payload.top_k = Number(top_k_raw);
  if (min_score_raw && min_score_raw !== "") payload.min_score = Number(min_score_raw);
  payload.lang_strict = lang_strict_raw === "on";
  await apiFetch("/tweaks/me", { method: "PATCH", body: payload });
  redirect("/tweaks?saved=1");
}

type Props = { searchParams: Promise<{ saved?: string }> };

export default async function TweaksPage({ searchParams }: Props) {
  const locale = await getLocale();
  const tr = (k: string) => t(k, locale);
  const sp = await searchParams;
  let tw: Tweaks = { top_k: null, min_score: null, lang_strict: null, ratio_overrides: null, sampling_overrides: null };
  try {
    tw = await apiFetch<Tweaks>("/tweaks/me");
  } catch {
    // first visit, no row yet
  }
  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-1 text-xl font-semibold">{tr("tweaks.title")}</h1>
      <p className="mb-4 text-sm text-fg-muted">{tr("tweaks.subtitle")}</p>
      {sp.saved && (
        <p className="mb-3 rounded-md border border-success bg-success/5 px-3 py-2 text-sm text-success">
          {tr("common.saved")}
        </p>
      )}
      <form action={patchTweaks} className="space-y-4 rounded-lg border border-border bg-bg p-5">
        <Field name="top_k" label={tr("tweaks.retrieval_top_k")} defaultValue={tw.top_k} hint={tr("tweaks.top_k_hint")} />
        <Field
          name="min_score"
          label={tr("tweaks.refusal_threshold")}
          defaultValue={tw.min_score}
          hint={tr("tweaks.min_score_hint")}
          step="0.01"
        />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="lang_strict" defaultChecked={!!tw.lang_strict} />
          <span>{tr("tweaks.strict_hebrew")}</span>
        </label>
        <Button type="submit">{tr("common.save")}</Button>
      </form>
    </div>
  );
}

function Field({
  name,
  label,
  defaultValue,
  hint,
  step,
}: {
  name: string;
  label: string;
  defaultValue: number | null;
  hint: string;
  step?: string;
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium">{label}</span>
      <input
        type="number"
        name={name}
        defaultValue={defaultValue ?? ""}
        step={step}
        className="mt-1 w-full rounded-md border border-border bg-bg-elev px-3 py-2 text-sm"
      />
      <span className="mt-1 block text-xs text-fg-muted">{hint}</span>
    </label>
  );
}
