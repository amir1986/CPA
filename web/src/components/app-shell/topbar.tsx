"use client";

import { useTheme } from "next-themes";
import { Moon, Sun, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";

export function Topbar() {
  const { resolvedTheme, setTheme } = useTheme();
  const locale = useLocale();
  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-bg px-4">
      <div className="flex items-center gap-2 text-sm text-fg-muted">
        <Search className="h-4 w-4" />
        <span>{t("nav.press", locale)} </span>
        <kbd className="rounded-sm border border-border-strong bg-bg-elev px-1.5 py-0.5 font-mono text-xs">
          ⌘K
        </kbd>
        <span> {t("nav.to_search", locale)}</span>
      </div>
      <div className="flex items-center gap-2">
        <Button
          size="icon"
          variant="ghost"
          aria-label={t("nav.toggle_theme", locale)}
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          {resolvedTheme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>
    </header>
  );
}
