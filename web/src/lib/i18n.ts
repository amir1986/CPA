/**
 * Tiny i18n helper used by both server and client components.
 *
 * Usage:
 *   import { t, useLocale } from "@/lib/i18n";
 *
 *   // Server component (locale from cookie):
 *   import { cookies } from "next/headers";
 *   const locale = (await cookies()).get("cpa_locale")?.value === "he" ? "he" : "en";
 *   t("nav.engagements", locale);
 *
 *   // Client component:
 *   const locale = useLocale();
 *   t("usgaap.confirm", locale);
 *
 * Missing keys gracefully fall back to English; placeholders use {var}.
 */

import { en } from "./i18n/en";
import { he } from "./i18n/he";

export type Locale = "en" | "he";

const DICTS = { en, he } as const;

export function isRTL(locale: Locale): boolean {
  return locale === "he";
}

export function t(
  key: string,
  locale: Locale = "en",
  vars: Record<string, string | number> = {},
): string {
  const out = lookup(key, locale) ?? lookup(key, "en") ?? key;
  if (!vars) return out;
  return out.replace(/\{(\w+)\}/g, (_, k) =>
    k in vars ? String(vars[k]) : `{${k}}`,
  );
}

function lookup(key: string, locale: Locale): string | undefined {
  const parts = key.split(".");
  let cur: unknown = DICTS[locale];
  for (const p of parts) {
    if (cur && typeof cur === "object" && p in (cur as Record<string, unknown>)) {
      cur = (cur as Record<string, unknown>)[p];
    } else {
      return undefined;
    }
  }
  return typeof cur === "string" ? cur : undefined;
}
