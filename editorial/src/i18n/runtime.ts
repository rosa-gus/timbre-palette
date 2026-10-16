import { selectMessage } from "../../../shared/i18n/messages.mjs";
import defaultMessages from "./catalog.en-US.generated";
import { writable, derived } from "svelte/store";
import { STORAGE_KEYS } from "../../../web/src/utils/storage-keys";
import type { MessageParameters, PluralParameters } from "./message-parameters.generated";

export const supportedLocales = ["pt-BR", "en-US"] as const;
export type Locale = typeof supportedLocales[number];
export const fallbackLocale: Locale = "en-US";
export let locale: Locale = fallbackLocale;
let messages: Record<string, unknown> = defaultMessages;
const activeLocale = writable<Locale>(locale);
export const localeStore = { subscribe: activeLocale.subscribe };
export const translation = derived<typeof localeStore, typeof t>(localeStore, () => t);
const preferenceKey = STORAGE_KEYS.editorialLocale;
let selection = 0;

export function matchLocale(value: string | null | undefined): Locale | null {
  if (!value) return null;
  try {
    const tag = Intl.getCanonicalLocales(value)[0];
    if (supportedLocales.includes(tag as Locale)) return tag as Locale;
    const language = tag.split("-")[0];
    return language === "en" ? "en-US" : language === "pt" ? "pt-BR" : null;
  } catch { return null; }
}

export function resolveLocale(query: string | null, saved: string | null, languages: readonly string[]): Locale {
  return matchLocale(query) ?? matchLocale(saved) ?? languages.map(matchLocale).find((value) => value !== null) ?? fallbackLocale;
}

export async function setLocale(next: Locale, options: { persist?: boolean; updateUrl?: boolean } = {}): Promise<void> {
  const request = ++selection;
  const catalog = next === "pt-BR" ? (await import("./catalog.generated")).default : defaultMessages;
  if (request !== selection) return;
  messages = catalog;
  locale = next;
  updateDocument();
  activeLocale.set(next);
  if (options.persist !== false) { try { localStorage.setItem(preferenceKey, next); } catch { /* Optional preference. */ } }
  if (options.updateUrl !== false && typeof window !== "undefined") {
    const url = new URL(window.location.href);
    url.searchParams.set("lang", next);
    window.history.replaceState(window.history.state, "", url);
  }
}

function updateDocument(): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = locale;
  document.documentElement.dir = "ltr";

}
type MessageKeys<Value> = {
  [Key in keyof Value & string]: Value[Key] extends string ? Key
    : Value[Key] extends Record<string, unknown> ? `${Key}.${MessageKeys<Value[Key]>}` : never;
}[keyof Value & string];
export type MessageKey = MessageKeys<typeof defaultMessages>;

type MessageArguments<Key extends MessageKey> =
  [MessageParameters[Key]] extends [never]
    ? []
    : [values: { [Name in MessageParameters[Key]]: Name extends PluralParameters[Key] ? number : string | number }];

/** Resolve catalog transforms without parsing external values as tags. */
export function t<Key extends MessageKey>(key: Key, ...args: MessageArguments<Key>): string {
  const selected = messageText(key, args[0]);
  return interpolateUpper(selected.text, selected.values, key);
}

function interpolate(text: string, values: Record<string, string | number> | undefined, key: MessageKey): string {
  return text.replace(/\{([^{}]+)\}/g, (_, name: string) => {
    if (!values || !Object.hasOwn(values, name)) {
      throw new Error(`Missing message parameter: ${key}.${name}`);
    }
    return String(values[name]);
  });
}

function interpolateUpper(text: string, values: Record<string, string | number> | undefined, key: MessageKey): string {
  return text.split(/<upper>(.*?)<\/upper>/gs).map((part, index) => {
    const rendered = interpolate(part, values, key);
    return index % 2 ? rendered.toLocaleUpperCase(locale) : rendered;
  }).join("");
}

export async function initializeLocale(): Promise<void> {
  let saved: string | null = null;
  try { saved = localStorage.getItem(preferenceKey); } catch { /* Optional preference. */ }
  const query = typeof window === "undefined" ? null : new URL(window.location.href).searchParams.get("lang");
  const languages = typeof navigator === "undefined" ? []
    : navigator.languages?.length ? navigator.languages
    : navigator.language ? [navigator.language] : [];
  const selected = resolveLocale(query, saved, languages);
  try { await setLocale(selected, { persist: false, updateUrl: false }); }
  catch { await setLocale(fallbackLocale, { persist: false, updateUrl: false }); }
}

/** Source nesting does not change the full keys used by callers. */
function messageText(key: MessageKey, values?: Record<string, string | number>) {
  for (const [catalog, language] of [[messages, locale], [defaultMessages, fallbackLocale]] as const) {
    let value: unknown = catalog;
    for (const segment of key.split(".")) {
      value = value && typeof value === "object" && Object.hasOwn(value, segment)
        ? (value as Record<string, unknown>)[segment] : undefined;
    }
    if (typeof value === "string" && value.trim()) return selectMessage(value, values, language, locale);
  }
  throw new Error(`Missing fallback message: ${key}`);
}
