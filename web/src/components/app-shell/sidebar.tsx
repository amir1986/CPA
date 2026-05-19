"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
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

const PRIMARY: Item[] = [
  { href: "/engagements", label: "Engagements", icon: LayoutDashboard },
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/books", label: "Books", icon: BookOpen },
  { href: "/analysis", label: "Analysis", icon: BarChart3 },
  { href: "/audit", label: "Audit", icon: ClipboardCheck },
  { href: "/compare", label: "GAAP vs IFRS", icon: GitCompareArrows },
  { href: "/traces", label: "Traces", icon: ScanSearch },
];

const SECONDARY: Item[] = [
  { href: "/sources", label: "Sources", icon: Network },
  { href: "/admin", label: "Admin", icon: Shield },
  { href: "/settings/profile", label: "Settings", icon: Settings },
  { href: "/tweaks", label: "Tweaks", icon: SlidersHorizontal },
];

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
  return (
    <aside className="flex h-screen w-60 shrink-0 flex-col border-e border-border bg-bg">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="grid h-8 w-8 place-items-center rounded-md bg-brand text-brand-fg font-bold">
          C
        </div>
        <div className="text-sm font-semibold leading-tight">CPA AI</div>
      </div>
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-2">
        {PRIMARY.map((it) => (
          <NavLink key={it.href} item={it} active={pathname.startsWith(it.href)} />
        ))}
      </nav>
      <div className="space-y-0.5 border-t border-border px-2 py-2">
        {SECONDARY.map((it) => (
          <NavLink key={it.href} item={it} active={pathname.startsWith(it.href)} />
        ))}
      </div>
    </aside>
  );
}
