"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
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
  Settings,
  Shield,
  SlidersHorizontal,
} from "lucide-react";

import { useLocale } from "@/lib/i18n/client";
import { t, type Locale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Item = { href: string; label: string; icon: React.ComponentType<{ className?: string }> };

function buildItems(eid: string | undefined, locale: Locale): { primary: Item[]; secondary: Item[] } {
  const E = (path: string) => (eid ? `/engagements/${eid}${path}` : "/engagements");
  const tr = (k: string) => t(k, locale);
  return {
    primary: [
      { href: "/engagements", label: tr("nav.engagements"), icon: LayoutDashboard },
      ...(eid
        ? [
            { href: E(""), label: tr("nav.dashboard"), icon: LayoutDashboard },
            { href: E("/chat"), label: tr("nav.chat"), icon: MessageSquare },
            { href: E("/documents"), label: tr("nav.documents"), icon: FileText },
            { href: E("/books/trial-balance"), label: tr("nav.books"), icon: BookOpen },
            { href: E("/analysis"), label: tr("nav.analysis"), icon: BarChart3 },
            { href: E("/audit/samples"), label: tr("nav.audit"), icon: ClipboardCheck },
            { href: E("/compare"), label: tr("nav.compare"), icon: GitCompareArrows },
            { href: E("/traces"), label: tr("nav.traces"), icon: ScanSearch },
          ]
        : []),
    ],
    secondary: [
      { href: "/usgaap-ifrs", label: tr("nav.usgaap_ifrs"), icon: ArrowLeftRight },
      { href: "/sources", label: tr("nav.sources"), icon: Network },
      { href: "/admin", label: tr("nav.admin"), icon: Shield },
      { href: "/settings/profile", label: tr("nav.settings"), icon: Settings },
      { href: "/tweaks", label: tr("nav.tweaks"), icon: SlidersHorizontal },
    ],
  };
}

function NavLink({ item, active }: { item: Item; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors",
        active ? "bg-bg-elev text-fg" : "text-fg-muted hover:bg-bg-elev hover:text-fg"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span>{item.label}</span>
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const params = useParams<{ eid?: string }>();
  const locale = useLocale();
  const { primary, secondary } = buildItems(params.eid, locale);

  return (
    <aside className="flex h-screen w-60 shrink-0 flex-col border-e border-border bg-bg">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="grid h-8 w-8 place-items-center rounded-md bg-brand text-brand-fg font-bold">
          C
        </div>
        <div className="text-sm font-semibold leading-tight">CPA AI</div>
      </div>
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-2">
        {primary.map((it) => (
          <NavLink key={it.href} item={it} active={pathname === it.href || pathname.startsWith(it.href + "/")} />
        ))}
      </nav>
      <div className="space-y-0.5 border-t border-border px-2 py-2">
        {secondary.map((it) => (
          <NavLink key={it.href} item={it} active={pathname.startsWith(it.href)} />
        ))}
      </div>
    </aside>
  );
}
