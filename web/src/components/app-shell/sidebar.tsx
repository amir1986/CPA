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

import { cn } from "@/lib/utils";

type Item = { href: string; label: string; icon: React.ComponentType<{ className?: string }> };

function buildItems(eid: string | undefined): { primary: Item[]; secondary: Item[] } {
  const E = (path: string) => (eid ? `/engagements/${eid}${path}` : "/engagements");
  return {
    primary: [
      { href: "/engagements", label: "Engagements", icon: LayoutDashboard },
      ...(eid
        ? [
            { href: E(""), label: "Dashboard", icon: LayoutDashboard },
            { href: E("/chat"), label: "Chat", icon: MessageSquare },
            { href: E("/documents"), label: "Documents", icon: FileText },
            { href: E("/books/trial-balance"), label: "Books", icon: BookOpen },
            { href: E("/analysis"), label: "Analysis", icon: BarChart3 },
            { href: E("/audit/samples"), label: "Audit", icon: ClipboardCheck },
            { href: E("/compare"), label: "Compare", icon: GitCompareArrows },
            { href: E("/traces"), label: "Traces", icon: ScanSearch },
          ]
        : []),
    ],
    secondary: [
      { href: "/usgaap-ifrs", label: "USGAAP <> IFRS", icon: ArrowLeftRight },
      { href: "/sources", label: "Sources", icon: Network },
      { href: "/admin", label: "Admin", icon: Shield },
      { href: "/settings/profile", label: "Settings", icon: Settings },
      { href: "/tweaks", label: "Tweaks", icon: SlidersHorizontal },
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
  const { primary, secondary } = buildItems(params.eid);

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
