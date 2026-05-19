import { redirect } from "next/navigation";

import { Button } from "@/components/ui/button";
import { apiFetch, ApiError } from "@/lib/api/client";
import type { Sample } from "@/lib/api/types";

type Props = { params: Promise<{ eid: string }>; searchParams: Promise<{ id?: string }> };

async function drawSample(formData: FormData) {
  "use server";
  const eid = String(formData.get("eid"));
  const size = Number(formData.get("size") ?? 25);
  const seed = Number(formData.get("seed") ?? 42);
  try {
    const s = await apiFetch<Sample>(`/engagements/${eid}/audit/samples`, {
      method: "POST",
      body: { method: "random", size, seed },
    });
    redirect(`/engagements/${eid}/audit/samples?id=${s.id}`);
  } catch (e) {
    if (e instanceof ApiError) {
      redirect(`/engagements/${eid}/audit/samples?error=${encodeURIComponent(e.problem.detail)}`);
    }
    throw e;
  }
}

export default async function SamplesPage({ params, searchParams }: Props) {
  const { eid } = await params;
  const sp = await searchParams;
  const error = (sp as Record<string, string>).error;

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-1 text-xl font-semibold">Audit sampling</h1>
      <p className="mb-4 text-sm text-fg-muted">
        Random sample with a fixed seed → reruns reproduce the same selected IDs.
      </p>
      <form action={drawSample} className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-border bg-bg p-4 md:grid-cols-4">
        <input type="hidden" name="eid" value={eid} />
        <label className="text-sm">
          <span className="block text-xs text-fg-muted">Size</span>
          <input type="number" name="size" defaultValue={25} min={1} max={500} className="mt-1 w-full rounded-md border border-border bg-bg-elev px-2 py-1" />
        </label>
        <label className="text-sm">
          <span className="block text-xs text-fg-muted">Seed</span>
          <input type="number" name="seed" defaultValue={42} className="mt-1 w-full rounded-md border border-border bg-bg-elev px-2 py-1" />
        </label>
        <div className="flex items-end md:col-span-2">
          <Button type="submit">Draw sample</Button>
        </div>
      </form>

      {error && <p className="mb-4 rounded-md border border-danger bg-danger/5 px-3 py-2 text-sm text-danger">{error}</p>}

      <p className="text-sm text-fg-muted">
        Samples are persisted in <code className="font-mono">samples</code> with their seed and
        population query. Re-drawing with the same seed produces an identical ID list — a CI test
        asserts this.
      </p>
    </div>
  );
}
