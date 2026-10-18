import { expect, it } from "vitest";
import registry from "../../shared/i18n/locales.json";
import { supportedLocales, fallbackLocale, languageNames, matchLocale, resolveLocale } from "../../shared/i18n/locales.mjs";
import * as web from "../src/i18n/runtime";
import * as editorial from "../../editorial/src/i18n/runtime";
import { catalogLoaders as webLoaders } from "../src/i18n/catalog-loaders.generated";
import { catalogLoaders as editorialLoaders } from "../../editorial/src/i18n/catalog-loaders.generated";
import { formattingCatalogs, narrativesCatalogs } from "../src/i18n/presentation-catalogs.generated";
import { validateLocaleDirectories } from "../../scripts/generate_locale_types.mjs";

it("uses one registry for both runtimes, loaders, selectors and synchronous presentation catalogs", () => {
  expect(supportedLocales).toEqual(Object.keys(registry.locales));
  expect(web.supportedLocales).toBe(supportedLocales);
  expect(editorial.supportedLocales).toBe(supportedLocales);
  expect(web.matchLocale).toBe(matchLocale);
  expect(editorial.matchLocale).toBe(matchLocale);
  expect(web.resolveLocale).toBe(resolveLocale);
  expect(editorial.resolveLocale).toBe(resolveLocale);
  expect(web.fallbackLocale).toBe(fallbackLocale);
  expect(editorial.fallbackLocale).toBe(fallbackLocale);
  for (const catalogs of [webLoaders, editorialLoaders, formattingCatalogs, narrativesCatalogs])
    expect(Object.keys(catalogs)).toEqual([...supportedLocales]);
  for (const tag of supportedLocales) expect(languageNames[tag]).toBe(registry.locales[tag].name);
});

it("retains canonical matching, explicit language fallbacks and preference precedence", () => {
  expect(matchLocale("PT-pt")).toBe("pt-BR");
  expect(matchLocale("en-GB")).toBe("en-US");
  expect(matchLocale("de-DE")).toBeNull();
  expect(matchLocale("invalid_tag")).toBeNull();
  expect(resolveLocale("en", "pt-BR", ["pt-BR"])).toBe("en-US");
  expect(resolveLocale(null, null, ["ja", "pt-PT"])).toBe("pt-BR");
  expect(resolveLocale(null, null, [])).toBe(fallbackLocale);
});

it("rejects missing or unregistered locale directories instead of silently omitting them", () => {
  expect(() => validateLocaleDirectories([...supportedLocales], "web")).not.toThrow();
  expect(() => validateLocaleDirectories([...supportedLocales, "fr"], "web")).toThrow("unregistered: fr");
  expect(() => validateLocaleDirectories(["pt-BR"], "editorial")).toThrow("missing: en-US");
});
