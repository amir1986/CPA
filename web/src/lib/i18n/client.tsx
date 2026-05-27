"use client";

import { createContext, useContext } from "react";

import type { Locale } from "../i18n";

const LocaleContext = createContext<Locale>("en");

export function LocaleProvider({
  value,
  children,
}: {
  value: Locale;
  children: React.ReactNode;
}) {
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): Locale {
  return useContext(LocaleContext);
}
