import registry from "./locales.json" with { type: "json" };

export const supportedLocales = Object.freeze(Object.keys(registry.locales));
export const fallbackLocale = registry.fallbackLocale;
export const localeDefinitions = registry.locales;
export const languageNames = Object.freeze(Object.fromEntries(supportedLocales.map((tag) => [tag, registry.locales[tag].name])));

const filenames = new Set();
for (const tag of supportedLocales) {
  const { name, catalog } = registry.locales[tag];
  if (Intl.getCanonicalLocales(tag)[0] !== tag || !name.trim() ||
      !/^catalog(?:\.[A-Za-z0-9-]+)?\.generated\.ts$/.test(catalog) || filenames.has(catalog))
    throw new Error(`Invalid locale registry entry: ${tag}`);
  filenames.add(catalog);
}
if (!supportedLocales.includes(fallbackLocale) ||
    Object.values(registry.languageFallbacks).some((tag) => !supportedLocales.includes(tag)))
  throw new Error("Locale fallbacks must reference registered locales");

export function matchLocale(value) {
  if (!value) return null;
  try {
    const tag = Intl.getCanonicalLocales(value)[0];
    return supportedLocales.includes(tag) ? tag : registry.languageFallbacks[tag.split("-")[0]] ?? null;
  } catch { return null; }
}

export function resolveLocale(query, saved, languages) {
  return matchLocale(query) ?? matchLocale(saved) ?? languages.map(matchLocale).find((tag) => tag !== null) ?? fallbackLocale;
}
