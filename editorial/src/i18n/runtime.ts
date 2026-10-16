import messages from "./catalog.generated";
import type { MessageParameters } from "./message-parameters.generated";

export const locale = "pt-BR";
export const supportedLocales = [locale] as const;
type MessageKeys<Value> = {
  [Key in keyof Value & string]: Value[Key] extends string ? Key
    : Value[Key] extends Record<string, unknown> ? `${Key}.${MessageKeys<Value[Key]>}` : never;
}[keyof Value & string];
export type MessageKey = MessageKeys<typeof messages>;

type MessageArguments<Key extends MessageKey> =
  [MessageParameters[Key]] extends [never]
    ? []
    : [values: Record<MessageParameters[Key], string | number>];

/** Resolve catalog transforms without parsing external values as tags. */
export function t<Key extends MessageKey>(key: Key, ...args: MessageArguments<Key>): string {
  return interpolateUpper(messageText(key), args[0], key);
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

export function initializeLocale(): void {
  document.documentElement.lang = locale;
  document.documentElement.dir = "ltr";
}

/** Source nesting does not change the full keys used by callers. */
function messageText(key: MessageKey): string {
  let value: unknown = messages;
  for (const segment of key.split(".")) {
    if (!value || typeof value !== "object" || !Object.hasOwn(value, segment)) {
      throw new Error(`Unknown message: ${key}`);
    }
    value = (value as Record<string, unknown>)[segment];
  }
  if (typeof value !== "string") throw new Error(`Invalid message: ${key}`);
  return value;
}
