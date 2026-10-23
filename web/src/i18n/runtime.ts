import { selectMessage } from "../../../shared/i18n/messages.mjs";
import { defaultMessages, catalogLoaders } from "./catalog-loaders.generated";
import { supportedLocales, fallbackLocale, matchLocale, resolveLocale, type Locale } from "../../../shared/i18n/locales.mjs";
import { writable, derived } from "svelte/store";
import { STORAGE_KEYS } from "../utils/storage-keys";
import type { MessageParameters, PluralParameters } from "./message-parameters.generated";

export { supportedLocales, fallbackLocale, matchLocale, resolveLocale, type Locale };

export let locale: Locale = fallbackLocale;
let messages: Record<string, unknown> = defaultMessages;
const activeLocale = writable<Locale>(locale);
export const localeStore = { subscribe: activeLocale.subscribe };
export const translation = derived<typeof localeStore, typeof t>(
  localeStore,
  () => t,
);
const preferenceKey = STORAGE_KEYS.webLocale;
let selection = 0;

export async function setLocale(
  next: Locale,
  options: { persist?: boolean; updateUrl?: boolean } = {},
): Promise<void> {
  const request = ++selection;
  const catalog = next === fallbackLocale ? defaultMessages : await catalogLoaders[next]();
  if (request !== selection) return;
  messages = catalog;
  locale = next;
  updateDocument();
  activeLocale.set(next);
  if (options.persist !== false) {
    try {
      localStorage.setItem(preferenceKey, next);
    } catch {
      /* Optional preference. */
    }
  }
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
  if (typeof document.querySelector !== "function") return;
  document.title = t("metadata.title");
  const metadata: Record<string, string> = {
    'meta[name="description"]': t("metadata.description"),
    'meta[property="og:locale"]': locale.replace("-", "_"),
    'meta[property="og:title"]': t("metadata.socialTitle"),
    'meta[property="og:description"]': t("metadata.description"),
    'meta[property="og:image:alt"]': t("metadata.imageAlt"),
    'meta[name="twitter:title"]': t("metadata.socialTitle"),
    'meta[name="twitter:description"]': t("metadata.description"),
    'meta[name="twitter:image:alt"]': t("metadata.imageAlt"),
  };
  for (const [selector, content] of Object.entries(metadata))
    document.querySelector(selector)?.setAttribute("content", content);
}
type MessageKeys<Value> = {
  [Key in keyof Value & string]: Value[Key] extends string
    ? Key
    : Value[Key] extends Record<string, unknown>
      ? `${Key}.${MessageKeys<Value[Key]>}`
      : never;
}[keyof Value & string];
export type MessageKey = MessageKeys<typeof defaultMessages>;

type MessageArguments<Key extends MessageKey> = [
  MessageParameters[Key],
] extends [never]
  ? []
  : [values: { [Name in MessageParameters[Key]]: Name extends PluralParameters[Key] ? number : string | number }];

/** Resolve catalog transforms without parsing external values as tags. */
export function t<Key extends MessageKey>(
  key: Key,
  ...args: MessageArguments<Key>
): string {
  const selected = messageText(key, args[0]);
  return interpolateUpper(selected.text, selected.values, key);
}

function interpolate(
  text: string,
  values: Record<string, string | number> | undefined,
  key: MessageKey,
): string {
  return text.replace(/\{([^{}]+)\}/g, (_, name: string) => {
    if (!values || !Object.hasOwn(values, name)) {
      throw new Error(`Missing message parameter: ${key}.${name}`);
    }
    return String(values[name]);
  });
}

function interpolateUpper(
  text: string,
  values: Record<string, string | number> | undefined,
  key: MessageKey,
): string {
  return text
    .replace(/<\/?(?!upper\b)[a-z]+>/g, "")
    .split(/<upper>(.*?)<\/upper>/gs)
    .map((part, index) => {
      const rendered = interpolate(part, values, key);
      return index % 2 ? rendered.toLocaleUpperCase(locale) : rendered;
    })
    .join("");
}

export async function initializeLocale(): Promise<void> {
  let saved: string | null = null;
  try {
    saved = localStorage.getItem(preferenceKey);
  } catch {
    /* Optional preference. */
  }
  const query =
    typeof window === "undefined"
      ? null
      : new URL(window.location.href).searchParams.get("lang");
  const languages = typeof navigator === "undefined" ? []
    : navigator.languages?.length ? navigator.languages
    : navigator.language ? [navigator.language] : [];
  const selected = resolveLocale(query, saved, languages);
  try {
    await setLocale(selected, { persist: false, updateUrl: false });
  } catch {
    await setLocale(fallbackLocale, { persist: false, updateUrl: false });
  }
}

/** Named wrappers preserve component-owned markup without rendering HTML. */
export function messageParts(
  key: MessageKey,
  values: Record<string, string | number> = {},
  language: Locale = locale,
): { text: string; wrapper?: string }[] {
  const parts: { text: string; wrapper?: string }[] = [];
  const selected = messageText(key, values);
  const source = selected.text;
  values = selected.values;
  const wrappers = /<([a-z]+)>(.*?)<\/\1>/gs;
  let start = 0;
  for (const match of source.matchAll(wrappers)) {
    parts.push({
      text: interpolate(source.slice(start, match.index), values, key),
    });
    const text = interpolate(match[2], values, key);
    parts.push(
      match[1] === "upper"
        ? { text: text.toLocaleUpperCase(language) }
        : { text, wrapper: match[1] },
    );
    start = match.index + match[0].length;
  }
  parts.push({ text: interpolate(source.slice(start), values, key) });
  return parts;
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
