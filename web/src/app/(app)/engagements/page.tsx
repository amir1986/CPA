import { Button } from "@/components/ui/button";

export default function EngagementsPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Engagements</h1>
        <p className="mt-1 text-sm text-fg-muted">
          A workspace per client engagement — audit, review, compilation, tax, or bookkeeping.
        </p>
      </header>

      <div className="rounded-lg border border-border bg-bg p-10 text-center">
        <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-full bg-bg-elev">
          <span className="text-xl">📁</span>
        </div>
        <h2 className="text-base font-medium">No engagements yet</h2>
        <p className="mx-auto mt-1 max-w-sm text-sm text-fg-muted">
          Create your first engagement to upload trial balances, run audit tests, and chat with the
          standards.
        </p>
        <div className="mt-5">
          <Button>Create engagement</Button>
        </div>
      </div>
    </div>
  );
}
