import registry from "./locales.json";
export type Locale = keyof typeof registry.locales;
export const supportedLocales: readonly Locale[];
export const fallbackLocale: Locale;
export const localeDefinitions: typeof registry.locales;
export const languageNames: Readonly<Record<Locale, string>>;
export function matchLocale(value: string | null | undefined): Locale | null;
export function resolveLocale(query: string | null, saved: string | null, languages: readonly string[]): Locale;
