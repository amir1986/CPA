import { apiFetch, ApiError } from "@/lib/api/client";
import type { RotatorStatus } from "@/lib/api/types";

export default async function AdminPage() {
  let rotator: RotatorStatus | null = null;
  let forbidden = false;
  try {
    rotator = await apiFetch<RotatorStatus>("/admin/rotator");
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) forbidden = true;
    else throw e;
  }

  if (forbidden) {
    return (
      <div className="mx-auto max-w-3xl rounded-lg border border-danger bg-danger/5 p-6">
        <h1 className="text-lg font-semibold">Admin only</h1>
        <p className="mt-1 text-sm text-fg-muted">You need the admin role to view this page.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="mb-1 text-xl font-semibold">Admin</h1>
      <p className="mb-4 text-sm text-fg-muted">
        Backend: <code className="font-mono">{rotator?.backend ?? "unknown"}</code>
      </p>

      <h2 className="mb-2 text-sm font-medium">Key rotator</h2>
      {!rotator?.keys?.length ? (
        <p className="rounded-lg border border-dashed border-border bg-bg p-6 text-sm text-fg-muted">
          No keys reported. (FakeLLM backend has no real rotator state.)
        </p>
      ) : (
        <table className="w-full overflow-hidden rounded-lg border border-border bg-bg text-sm">
          <thead className="text-left text-xs uppercase text-fg-subtle">
            <tr>
              <th className="px-3 py-2">Key</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2 text-right">Requests</th>
              <th className="px-3 py-2 text-right">Failures</th>
              <th className="px-3 py-2">Last error</th>
              <th className="px-3 py-2 text-right">Cooldown</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rotator.keys.map((k, i) => (
              <tr key={i} className={i === rotator.cursor ? "bg-brand/5" : ""}>
                <td className="px-3 py-1.5 font-mono">{k.key}</td>
                <td className="px-3 py-1.5">
                  <span className={
                    "rounded-pill px-2 py-0.5 text-xs " +
                    (k.status === "active"
                      ? "bg-success/10 text-success"
                      : k.status === "cooling"
                        ? "bg-warning/10 text-warning"
                        : "bg-danger/10 text-danger")
                  }>
                    {k.status}
                  </span>
                </td>
                <td className="px-3 py-1.5 text-right font-mono">{k.requests}</td>
                <td className="px-3 py-1.5 text-right font-mono">{k.consecutive_failures}</td>
                <td className="px-3 py-1.5 text-fg-muted">{k.last_error ?? "—"}</td>
                <td className="px-3 py-1.5 text-right font-mono">
                  {k.cooldown_remaining ? `${k.cooldown_remaining.toFixed(0)}s` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
