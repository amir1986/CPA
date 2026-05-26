import { cookies } from "next/headers";

import type { Locale } from "@/lib/i18n";

export async function getLocale(): Promise<Locale> {
  const cookieStore = await cookies();
  return cookieStore.get("cpa_locale")?.value === "he" ? "he" : "en";
}
