import { cookies } from "next/headers";

import { Sidebar } from "@/components/app-shell/sidebar";
import { Topbar } from "@/components/app-shell/topbar";
import { LocaleProvider } from "@/lib/i18n/client";
import type { Locale } from "@/lib/i18n";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  // Same cookie the root layout reads to flip <html dir>. Client components
  // get it via the LocaleProvider context so t() works without prop-drilling.
  const cookieStore = await cookies();
  const locale: Locale = cookieStore.get("cpa_locale")?.value === "en" ? "en" : "he";
  return (
    <LocaleProvider value={locale}>
      <div className="flex min-h-screen bg-bg-elev">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar />
          <main className="flex-1 overflow-y-auto p-6">{children}</main>
        </div>
      </div>
    </LocaleProvider>
  );
}
