"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Send } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { Citation } from "@/lib/api/types";

type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  citations: Citation[];
  refused?: boolean;
  language?: string;
};

type StreamEvent =
  | { type: "token"; delta: string }
  | { type: "citation"; data: Citation }
  | { type: "done"; refused: boolean; language: string };

function uuid(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

async function* parseSSE(res: Response): AsyncGenerator<StreamEvent> {
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      try {
        const json = JSON.parse(data);
        if (event === "token") yield { type: "token", delta: json.delta };
        else if (event === "citation") yield { type: "citation", data: json };
        else if (event === "done") yield { type: "done", refused: !!json.refused, language: json.language };
      } catch {
        // ignore malformed frame
      }
    }
  }
}

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [openCitation, setOpenCitation] = useState<Citation | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    const userMsg: Message = { id: uuid(), role: "user", text, citations: [] };
    const assistantMsg: Message = { id: uuid(), role: "assistant", text: "", citations: [] };
    setMessages((m) => [...m, userMsg, assistantMsg]);
    setInput("");
    setBusy(true);
    try {
      const res = await fetch("/api/stream/query/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });
      for await (const evt of parseSSE(res)) {
        if (evt.type === "token") {
          setMessages((ms) =>
            ms.map((m) => (m.id === assistantMsg.id ? { ...m, text: m.text + evt.delta } : m)),
          );
        } else if (evt.type === "citation") {
          setMessages((ms) =>
            ms.map((m) =>
              m.id === assistantMsg.id ? { ...m, citations: [...m.citations, evt.data] } : m,
            ),
          );
        } else if (evt.type === "done") {
          setMessages((ms) =>
            ms.map((m) =>
              m.id === assistantMsg.id ? { ...m, refused: evt.refused, language: evt.language } : m,
            ),
          );
        }
      }
    } catch {
      setMessages((ms) =>
        ms.map((m) =>
          m.id === assistantMsg.id ? { ...m, text: "[error contacting backend]", refused: true } : m,
        ),
      );
    } finally {
      setBusy(false);
    }
  }, [busy, input]);

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col">
      <div className="flex-1 overflow-y-auto pr-3" dir="ltr">
        {messages.length === 0 && (
          <div className="mx-auto mt-12 max-w-xl rounded-lg border border-dashed border-border bg-bg p-8 text-center">
            <h2 className="text-base font-medium">Ask a question</h2>
            <p className="mt-2 text-sm text-fg-muted">
              Try: <em>“When is revenue recognized under ASC 606?”</em>
            </p>
          </div>
        )}
        <ul className="space-y-4">
          {messages.map((m) => (
            <li
              key={m.id}
              className={
                m.role === "user"
                  ? "ml-auto max-w-2xl rounded-lg bg-brand/10 px-4 py-2 text-sm"
                  : "max-w-3xl rounded-lg border border-border bg-bg px-4 py-3 text-sm"
              }
            >
              {m.role === "assistant" && m.refused && (
                <span className="mb-2 inline-block rounded-pill bg-refusal/10 px-2 py-0.5 text-xs font-medium text-refusal">
                  refused — out of corpus
                </span>
              )}
              <p className="whitespace-pre-wrap">{m.text || (m.role === "assistant" && busy ? "…" : "")}</p>
              {m.citations.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {m.citations.map((c, i) => (
                    <button
                      key={i}
                      onClick={() => setOpenCitation(c)}
                      className="rounded-pill border border-border-strong bg-bg-elev px-2 py-0.5 font-mono text-xs hover:bg-brand/10"
                    >
                      [{c.standard ?? c.url.replace(/^https?:\/\//, "").slice(0, 24)}]
                    </button>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
        <div ref={endRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
        className="mt-3 flex gap-2 border-t border-border pt-3"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about accounting, auditing, or tax standards…"
          rows={2}
          className="flex-1 resize-none rounded-md border border-border bg-bg px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <Button type="submit" disabled={busy || !input.trim()}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </Button>
      </form>

      {openCitation && <CitationDrawer citation={openCitation} onClose={() => setOpenCitation(null)} />}
    </div>
  );
}

function CitationDrawer({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex items-stretch bg-bg-overlay" onClick={onClose}>
      <div
        className="ms-auto h-full w-full max-w-md overflow-y-auto border-s border-border bg-bg p-5 shadow-e4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">Citation</h2>
          <button onClick={onClose} className="text-fg-muted hover:text-fg">×</button>
        </div>
        <dl className="space-y-2 text-sm">
          {citation.standard && (
            <div>
              <dt className="text-xs uppercase text-fg-subtle">Standard</dt>
              <dd className="font-mono">{citation.standard}</dd>
            </div>
          )}
          {citation.paragraph && (
            <div>
              <dt className="text-xs uppercase text-fg-subtle">Paragraph</dt>
              <dd className="font-mono">{citation.paragraph}</dd>
            </div>
          )}
          <div>
            <dt className="text-xs uppercase text-fg-subtle">URL</dt>
            <dd>
              <a href={citation.url} target="_blank" rel="noreferrer" className="text-brand underline">
                {citation.url}
              </a>
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase text-fg-subtle">Quote</dt>
            <dd className="rounded-md bg-bg-elev p-3 text-sm">{citation.quote}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
