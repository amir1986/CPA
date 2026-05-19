import Link from "next/link";
import { redirect } from "next/navigation";

import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api/client";
import type { Client, Engagement } from "@/lib/api/types";

async function createEngagement(formData: FormData) {
  "use server";
  const name = String(formData.get("name") ?? "").trim();
  const clientName = String(formData.get("client_name") ?? "").trim();
  const type = String(formData.get("type") ?? "audit");
  if (!name || !clientName) redirect("/engagements?error=missing");

  // Ensure a client row exists; first match by name, else create.
  const clients = await apiFetch<Client[]>("/clients");
  let client = clients.find((c) => c.name === clientName);
  if (!client) {
    client = await apiFetch<Client>("/clients", {
      method: "POST",
      body: { name: clientName },
    });
  }
  const eng = await apiFetch<Engagement>("/engagements", {
    method: "POST",
    body: { client_id: client.id, name, type },
  });
  redirect(`/engagements/${eng.id}`);
}

export default async function EngagementsPage() {
  const engagements = await apiFetch<Engagement[]>("/engagements");
  const clients = await apiFetch<Client[]>("/clients");
  const clientName = (id: string) => clients.find((c) => c.id === id)?.name ?? id;

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Engagements</h1>
          <p className="mt-1 text-sm text-fg-muted">
            One workspace per client engagement — audit, review, compilation, tax, or bookkeeping.
          </p>
        </div>
      </header>

      <section className="mb-6 rounded-lg border border-border bg-bg p-5">
        <h2 className="mb-3 text-sm font-medium">Create engagement</h2>
        <form action={createEngagement} className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <input
            name="client_name"
            placeholder="Client name"
            required
            className="rounded-md border border-border bg-bg-elev px-3 py-2 text-sm"
          />
          <input
            name="name"
            placeholder="Engagement name"
            required
            className="rounded-md border border-border bg-bg-elev px-3 py-2 text-sm"
          />
          <select name="type" defaultValue="audit" className="rounded-md border border-border bg-bg-elev px-3 py-2 text-sm">
            <option value="audit">Audit</option>
            <option value="review">Review</option>
            <option value="compilation">Compilation</option>
            <option value="tax">Tax</option>
            <option value="bookkeeping">Bookkeeping</option>
          </select>
          <Button type="submit">Create</Button>
        </form>
      </section>

      {engagements.length === 0 ? (
        <div className="rounded-lg border border-border bg-bg p-10 text-center">
          <p className="text-base font-medium">No engagements yet</p>
          <p className="mt-1 text-sm text-fg-muted">Create your first engagement above.</p>
        </div>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-bg">
          {engagements.map((e) => (
            <li key={e.id}>
              <Link
                href={`/engagements/${e.id}`}
                className="flex items-center justify-between px-5 py-4 hover:bg-bg-elev"
              >
                <div>
                  <div className="text-sm font-medium">{e.name}</div>
                  <div className="text-xs text-fg-muted">
                    {clientName(e.client_id)} · {e.type} · {e.status}
                  </div>
                </div>
                <span className="text-xs font-mono text-fg-subtle">{e.id.slice(0, 8)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
