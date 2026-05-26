"use client";

import { useEffect, useRef, useState } from "react";
import type { Core, EventObject, Ext, LayoutOptions, NodeSingular, StylesheetJson } from "cytoscape";
import { Loader2, Search } from "lucide-react";
import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

type Node = {
  id: string;
  label: string;
  type: "concept" | "standard" | "paragraph";
  jurisdiction?: string | null;
  corpus_type?: string | null;
  language?: string | null;
  url?: string | null;
  excerpt?: string | null;
};

type Edge = {
  source: string;
  target: string;
  weight: number;
  kind: string;
};

type Graph = {
  nodes: Node[];
  edges: Edge[];
  truncated: boolean;
  chunk_count: number;
};

type Selected = Node | null;

const JURISDICTIONS = ["US", "IFRS", "IL"] as const;
const CORPUS_TYPES = ["accounting", "auditing", "tax"] as const;

export function KnowledgeGraph({ initial }: { initial: Graph }) {
  const locale = useLocale();
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [graph, setGraph] = useState<Graph>(initial);
  const [jurisdictions, setJurisdictions] = useState<Set<string>>(new Set());
  const [corpusTypes, setCorpusTypes] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Selected>(null);
  const [search, setSearch] = useState("");

  // Initialize Cytoscape once.
  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;
    (async () => {
      const cytoscape = (await import("cytoscape")).default;
      const fcose = (await import("cytoscape-fcose")).default;
      if (cancelled) return;
      cytoscape.use(fcose as unknown as Ext);

      const cy: Core = cytoscape({
        container: containerRef.current,
        elements: toElements(graph),
        style: GRAPH_STYLE as unknown as StylesheetJson,
        layout: { name: "fcose", animate: false, randomize: false } as LayoutOptions,
        wheelSensitivity: 0.4,
      });
      cy.on("tap", "node", (e: EventObject) => {
        setSelected(e.target.data() as Node);
      });
      cy.on("tap", (e: EventObject) => {
        if (e.target === cy) setSelected(null);
      });
      cyRef.current = cy;
    })();
    return () => {
      cancelled = true;
      cyRef.current?.destroy?.();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-render when graph data changes.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().remove();
    cy.add(toElements(graph));
    cy.layout({ name: "fcose", animate: false, randomize: false } as LayoutOptions).run();
  }, [graph]);

  // Focus / fade on search.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const q = search.trim().toLowerCase();
    cy.nodes().forEach((n: NodeSingular) => {
      const data = n.data() as Node;
      const hit = !q || data.label.toLowerCase().includes(q);
      n.removeClass("dim");
      if (q && !hit) n.addClass("dim");
    });
  }, [search]);

  // Fetch new graph when filters change.
  useEffect(() => {
    const ctl = new AbortController();
    (async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        jurisdictions.forEach((j) => params.append("jurisdiction", j));
        corpusTypes.forEach((c) => params.append("corpus_type", c));
        const res = await fetch(`/api/cpa/knowledge/graph?${params.toString()}`, {
          signal: ctl.signal,
        });
        if (res.ok) {
          const data = (await res.json()) as Graph;
          setGraph(data);
        }
      } finally {
        setLoading(false);
      }
    })();
    return () => ctl.abort();
  }, [jurisdictions, corpusTypes]);

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_18rem]">
      <div className="rounded-lg border border-border bg-bg p-2">
        <div className="mb-2 flex items-center gap-2">
          <Search className="h-4 w-4 text-fg-subtle" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("sources.search_nodes", locale)}
            className="flex-1 rounded-md border border-border bg-bg-elev px-2 py-1 text-sm"
          />
          {loading && <Loader2 className="h-4 w-4 animate-spin text-fg-muted" />}
        </div>
        <div
          ref={containerRef}
          className="h-[640px] w-full rounded-md border border-border bg-bg-elev"
        />
        <div className="mt-2 flex items-center gap-3 text-xs text-fg-muted">
          <Legend color="var(--c-brand)" label={t("sources.concept", locale)} />
          <Legend color="var(--c-info)" label={t("sources.standard", locale)} />
          <Legend color="var(--c-fg-muted)" label={t("sources.paragraph", locale)} />
          <span className="ms-auto">
            {t("sources.graph_counts", locale, { nodes: graph.nodes.length, edges: graph.edges.length })}{" "}
            {graph.truncated ? t("sources.truncated", locale) : ""}
          </span>
        </div>
      </div>
      <aside className="space-y-4">
        <FilterGroup
          title={t("sources.jurisdiction", locale)}
          options={JURISDICTIONS}
          selected={jurisdictions}
          onToggle={(v) => setJurisdictions(toggle(jurisdictions, v))}
        />
        <FilterGroup
          title={t("sources.corpus_type", locale)}
          options={CORPUS_TYPES}
          selected={corpusTypes}
          onToggle={(v) => setCorpusTypes(toggle(corpusTypes, v))}
        />
        {selected ? (
          <NodeCard node={selected} />
        ) : (
          <p className="rounded-lg border border-dashed border-border bg-bg p-4 text-xs text-fg-muted">
            {t("sources.tap_node", locale)}
          </p>
        )}
      </aside>
    </div>
  );
}

function toggle(set: Set<string>, v: string): Set<string> {
  const next = new Set(set);
  if (next.has(v)) next.delete(v);
  else next.add(v);
  return next;
}

function toElements(graph: Graph) {
  return [
    ...graph.nodes.map((n) => ({ data: n })),
    ...graph.edges.map((e) => ({ data: { id: `${e.source}->${e.target}`, ...e } })),
  ];
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

function FilterGroup({
  title,
  options,
  selected,
  onToggle,
}: {
  title: string;
  options: readonly string[];
  selected: Set<string>;
  onToggle: (v: string) => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-bg p-3">
      <h3 className="mb-2 text-xs uppercase tracking-wide text-fg-subtle">{title}</h3>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const active = selected.has(o);
          return (
            <button
              key={o}
              onClick={() => onToggle(o)}
              className={
                "rounded-pill border px-2.5 py-1 text-xs " +
                (active
                  ? "border-brand bg-brand/10 text-brand"
                  : "border-border-strong bg-bg-elev hover:bg-bg")
              }
            >
              {o}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function NodeCard({ node }: { node: Node }) {
  return (
    <div className="rounded-lg border border-border bg-bg p-4 text-sm">
      <div className="mb-2 flex items-center gap-2">
        <span className="rounded-pill bg-bg-elev px-2 py-0.5 text-xs uppercase">{node.type}</span>
        {node.jurisdiction && (
          <span className="rounded-pill bg-bg-elev px-2 py-0.5 text-xs font-mono">
            {node.jurisdiction}
          </span>
        )}
      </div>
      <div className="text-base font-semibold">{node.label}</div>
      {node.url && (
        <a href={node.url} target="_blank" rel="noreferrer" className="mt-1 block text-xs text-brand underline">
          {node.url}
        </a>
      )}
      {node.excerpt && (
        <p className="mt-3 rounded-md border border-border bg-bg-elev p-2 text-xs">{node.excerpt}</p>
      )}
    </div>
  );
}

const GRAPH_STYLE = [
  {
    selector: "node",
    style: {
      "background-color": "var(--c-fg-muted)",
      label: "data(label)",
      "font-size": "10px",
      "text-valign": "center",
      "text-halign": "center",
      color: "var(--c-fg)",
      "text-background-color": "var(--c-bg)",
      "text-background-opacity": 0.9,
      "text-background-padding": "2px",
      width: 28,
      height: 28,
    },
  },
  {
    selector: 'node[type = "concept"]',
    style: { "background-color": "var(--c-brand)", shape: "round-rectangle", width: 60, height: 30 },
  },
  {
    selector: 'node[type = "standard"]',
    style: { "background-color": "var(--c-info)", width: 36, height: 36 },
  },
  {
    selector: 'node[type = "paragraph"]',
    style: { "background-color": "var(--c-fg-muted)", width: 20, height: 20, "font-size": "8px" },
  },
  {
    selector: "edge",
    style: {
      "curve-style": "bezier",
      width: 1.5,
      "line-color": "var(--c-border-strong)",
      "target-arrow-shape": "triangle",
      "target-arrow-color": "var(--c-border-strong)",
      opacity: 0.7,
    },
  },
  {
    selector: 'edge[kind = "equivalent"]',
    style: { "line-style": "dashed", "line-color": "var(--c-anomaly)", "target-arrow-color": "var(--c-anomaly)" },
  },
  {
    selector: ".dim",
    style: { opacity: 0.12 },
  },
];
