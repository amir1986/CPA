"use client";

/**
 * ⌘K command palette.
 *
 * Replaces the old "Press ⌘K to search" hint that had no keyboard handler
 * behind it. Renders a centred modal with a fuzzy-search input and a
 * filterable list of navigable destinations (sidebar items + USGAAP runs
 * if any). Keyboard: ⌘/Ctrl+K opens, ↑/↓ moves selection, ↵ navigates,
 * Esc closes.
 *
 * Locale-aware: every visible string flows through ``t()`` so the palette
 * is fully Hebrew when ``cpa_locale=he``.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeftRight,
  BarChart3,
  BookOpen,
  ClipboardCheck,
  FileText,
  GitCompareArrows,
  LayoutDashboard,
  MessageSquare,
  Network,
  ScanSearch,
  Search,
  Settings,
  Shield,
  SlidersHorizontal,
} from "lucide-react";

import { t, type Locale } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

type PaletteItem = {
  id: string;
  label: string;
  hint: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  section: "primary" | "secondary";
};

function buildItems(eid: string | undefined, locale: Locale): PaletteItem[] {
  const tr = (k: string) => t(k, locale);
  const E = (path: string) => (eid ? `/engagements/${eid}${path}` : "/engagements");
  const sectionPrimary = tr("nav.section_primary");
  const sectionSecondary = tr("nav.section_secondary");
  const items: PaletteItem[] = [
    { id: "engagements", label: tr("nav.engagements"), hint: sectionPrimary, href: "/engagements", icon: LayoutDashboard, section: "primary" },
  ];
  if (eid) {
    items.push(
      { id: "dashboard", label: tr("nav.dashboard"), hint: sectionPrimary, href: E(""), icon: LayoutDashboard, section: "primary" },
      { id: "chat", label: tr("nav.chat"), hint: sectionPrimary, href: E("/chat"), icon: MessageSquare, section: "primary" },
      { id: "documents", label: tr("nav.documents"), hint: sectionPrimary, href: E("/documents"), icon: FileText, section: "primary" },
      { id: "books", label: tr("nav.books"), hint: sectionPrimary, href: E("/books/trial-balance"), icon: BookOpen, section: "primary" },
      { id: "analysis", label: tr("nav.analysis"), hint: sectionPrimary, href: E("/analysis"), icon: BarChart3, section: "primary" },
      { id: "audit", label: tr("nav.audit"), hint: sectionPrimary, href: E("/audit/samples"), icon: ClipboardCheck, section: "primary" },
      { id: "compare", label: tr("nav.compare"), hint: sectionPrimary, href: E("/compare"), icon: GitCompareArrows, section: "primary" },
      { id: "traces", label: tr("nav.traces"), hint: sectionPrimary, href: E("/traces"), icon: ScanSearch, section: "primary" },
    );
  }
  items.push(
    { id: "usgaap-ifrs", label: tr("nav.usgaap_ifrs"), hint: sectionSecondary, href: "/usgaap-ifrs", icon: ArrowLeftRight, section: "secondary" },
    { id: "sources", label: tr("nav.sources"), hint: sectionSecondary, href: "/sources", icon: Network, section: "secondary" },
    { id: "admin", label: tr("nav.admin"), hint: sectionSecondary, href: "/admin", icon: Shield, section: "secondary" },
    { id: "settings", label: tr("nav.settings"), hint: sectionSecondary, href: "/settings/profile", icon: Settings, section: "secondary" },
    { id: "tweaks", label: tr("nav.tweaks"), hint: sectionSecondary, href: "/tweaks", icon: SlidersHorizontal, section: "secondary" },
  );
  return items;
}

function normalize(s: string): string {
  // Lowercase + strip Hebrew diacritics so a query types as "תקנים" still
  // matches a label rendered as "תקנים" with niqqud. Latin diacritics are
  // not used in our nav labels so this is sufficient.
  return s
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[֑-ׇֽֿׁׂׅׄ]/g, "");
}

export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const locale = useLocale();
  const params = useParams<{ eid?: string }>();
  const items = useMemo(() => buildItems(params.eid, locale), [params.eid, locale]);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const q = normalize(query.trim());
    if (!q) return items;
    return items.filter((it) => normalize(it.label).includes(q) || normalize(it.hint).includes(q));
  }, [items, query]);

  // Reset cursor whenever the visible result set changes — selecting the
  // 5th row of a 3-row list is a footgun otherwise.
  useEffect(() => {
    setCursor(0);
  }, [query, open]);

  useEffect(() => {
    if (!open) return;
    // Focus the input shortly after mount so the browser actually moves
    // focus (Next.js dialogs mounted via portals miss the first tick).
    const id = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [open]);

  const navigate = useCallback(
    (item: PaletteItem) => {
      onOpenChange(false);
      setQuery("");
      router.push(item.href);
    },
    [router, onOpenChange],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onOpenChange(false);
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setCursor((c) => Math.min(c + 1, filtered.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setCursor((c) => Math.max(c - 1, 0));
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const item = filtered[cursor];
        if (item) navigate(item);
      }
    },
    [filtered, cursor, navigate, onOpenChange],
  );

  // Keep the active row in view when the cursor moves past the visible
  // window — common UX for keyboard-driven list selection.
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const row = list.querySelector<HTMLElement>(`[data-cursor='${cursor}']`);
    row?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("nav.search_dialog_title", locale)}
      className="fixed inset-0 z-50 flex items-start justify-center bg-bg-overlay/60 p-4 pt-[12vh]"
      onClick={() => onOpenChange(false)}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border border-border bg-bg shadow-e4"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onKeyDown}
      >
        <div className="flex items-center gap-2 border-b border-border px-3 py-2">
          <Search className="h-4 w-4 text-fg-muted" aria-hidden />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("nav.search_input_placeholder", locale)}
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-fg-subtle"
            aria-label={t("nav.search_dialog_title", locale)}
          />
          <kbd className="rounded-sm border border-border-strong bg-bg-elev px-1.5 py-0.5 font-mono text-xs text-fg-muted">
            esc
          </kbd>
        </div>
        <div ref={listRef} className="max-h-[50vh] overflow-y-auto p-1">
          {filtered.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-fg-muted">
              {t("nav.search_no_results", locale)}
            </p>
          ) : (
            <ul role="listbox">
              {filtered.map((item, idx) => {
                const Icon = item.icon;
                const active = idx === cursor;
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      data-cursor={idx}
                      role="option"
                      aria-selected={active}
                      onMouseMove={() => setCursor(idx)}
                      onClick={() => navigate(item)}
                      className={
                        "flex w-full items-center gap-3 rounded-md px-3 py-2 text-start text-sm " +
                        (active ? "bg-bg-elev text-fg" : "text-fg-muted hover:bg-bg-elev hover:text-fg")
                      }
                    >
                      <Icon className="h-4 w-4 shrink-0" aria-hidden />
                      <span className="flex-1 truncate">{item.label}</span>
                      <span className="text-xs text-fg-subtle">{item.hint}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-border bg-bg-elev px-3 py-1.5 text-xs text-fg-subtle">
          <span>{t("nav.search_hint_navigate", locale)}</span>
          <span>{t("nav.search_hint_select", locale)}</span>
          <span>{t("nav.search_hint_close", locale)}</span>
        </div>
      </div>
    </div>
  );
}

/**
 * Window-level ⌘/Ctrl+K listener. Calls ``onToggle`` when the chord fires
 * so the parent component can toggle ``open`` state. Splitting this into
 * its own hook keeps Topbar focused on rendering.
 */
export function useCommandPaletteShortcut(onToggle: () => void): void {
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onToggle();
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onToggle]);
}
