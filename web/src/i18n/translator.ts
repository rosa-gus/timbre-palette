import { fallbackLocale } from "../../../shared/i18n/locales.mjs";
import { selectMessage } from "../../../shared/i18n/messages.mjs";
import type { Locale, MessageKey } from "./runtime";
import type { MessageParameters, PluralParameters } from "./message-parameters.generated";

type Catalog = Record<string, unknown>;
type Arguments<Key extends MessageKey> = [MessageParameters[Key]] extends [never] ? []
  : [values: { [Name in MessageParameters[Key]]: Name extends PluralParameters[Key] ? number : string | number }];

/** Translate synchronous presentation data without changing the active UI locale. */
export function createTranslator(catalog: Catalog, fallback: Catalog, language: Locale) {
  return <Key extends MessageKey>(key: Key, ...args: Arguments<Key>): string => {
    for (const [dictionary, messageLocale] of [[catalog, language], [fallback, fallbackLocale]] as const) {
      let value: unknown = dictionary;
      for (const segment of key.split("."))
        value = value && typeof value === "object" && Object.hasOwn(value, segment)
          ? (value as Catalog)[segment] : undefined;
      if (typeof value !== "string" || !value.trim()) continue;
      const selected = selectMessage(value, args[0], messageLocale, language);
      return selected.text.split(/<upper>(.*?)<\/upper>/gs).map((part, index) => {
        const rendered = part.replace(/\{([^{}]+)\}/g, (_, name: string) => {
          if (!Object.hasOwn(selected.values, name)) throw new Error(`Missing message parameter: ${key}.${name}`);
          return String(selected.values[name]);
        });
        return index % 2 ? rendered.toLocaleUpperCase(language) : rendered;
      }).join("");
    }
    throw new Error(`Missing fallback message: ${key}`);
  };
}
