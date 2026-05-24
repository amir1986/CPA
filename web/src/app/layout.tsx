import type { Metadata } from "next";
import { cookies } from "next/headers";
import { ThemeProvider } from "next-themes";

import "./globals.css";

export const metadata: Metadata = {
  title: "CPA AI Assistant",
  description:
    "AI-powered CPA workbench — knowledge, books, analysis, and audit, with citations.",
  applicationName: "CPA AI Assistant",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Locale is persisted as a client-readable cookie by /settings/profile so
  // SSR can flip <html dir> on the first render without an api round-trip.
  const cookieStore = await cookies();
  const locale = cookieStore.get("cpa_locale")?.value === "he" ? "he" : "en";
  const dir = locale === "he" ? "rtl" : "ltr";

  return (
    <html lang={locale} dir={dir} suppressHydrationWarning>
      <body>
        <a href="#main" className="skip-to-content">
          Skip to content
        </a>
        <ThemeProvider
          attribute="data-theme"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <div id="main" className="min-h-screen">
            {children}
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
