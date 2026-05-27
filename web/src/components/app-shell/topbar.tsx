"use client";

import { useCallback, useState } from "react";
import { useTheme } from "next-themes";
import { Moon, Sun, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { useLocale } from "@/lib/i18n/client";
import { CommandPalette, useCommandPaletteShortcut } from "./command-palette";

export function Topbar() {
  const { resolvedTheme, setTheme } = useTheme();
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const toggle = useCallback(() => setOpen((v) => !v), []);
  useCommandPaletteShortcut(toggle);

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-bg px-4">
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={t("nav.search_button", locale)}
        className="flex items-center gap-2 rounded-md border border-border bg-bg-elev px-3 py-1.5 text-sm text-fg-muted transition-colors hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        <Search className="h-4 w-4" aria-hidden />
        <span>{t("nav.search_button", locale)}</span>
        <span className="ms-1 hidden items-center gap-1 sm:flex">
          <kbd className="rounded-sm border border-border-strong bg-bg px-1.5 py-0.5 font-mono text-xs">
            ⌘K
          </kbd>
        </span>
      </button>
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
      <CommandPalette open={open} onOpenChange={setOpen} />
    </header>
  );
}
