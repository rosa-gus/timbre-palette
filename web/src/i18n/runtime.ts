import messages from "./locales/pt-BR";

export const locale = "pt-BR";
export const supportedLocales = [locale] as const;
export type MessageKey = keyof typeof messages;

type ParametersIn<Text extends string> =
  Text extends `${string}{${infer Name}}${infer Rest}`
    ? Name | ParametersIn<Rest>
    : never;
type MessageArguments<Key extends MessageKey> =
  [ParametersIn<(typeof messages)[Key]>] extends [never]
    ? []
    : [values: Record<ParametersIn<(typeof messages)[Key]>, string | number>];

/** Interpolate plain text; callers keep markup in their components. */
export function t<Key extends MessageKey>(key: Key, ...args: MessageArguments<Key>): string {
  return interpolate(messages[key], args[0], key);
}

function interpolate(text: string, values: Record<string, string | number> | undefined, key: MessageKey): string {
  return text.replace(/\{([^{}]+)\}/g, (_, name: string) => {
    if (!values || !Object.hasOwn(values, name)) {
      throw new Error(`Missing message parameter: ${key}.${name}`);
    }
    return String(values[name]);
  });
}

export function initializeLocale(): void {
  document.documentElement.lang = locale;
  document.documentElement.dir = "ltr";
}

/** Named wrappers preserve component-owned markup without rendering HTML. */
export function messageParts(key: MessageKey, values: Record<string, string | number> = {}): { text: string; wrapper?: string }[] {
  const parts: { text: string; wrapper?: string }[] = [];
  const source = messages[key];
  const wrappers = /<([a-z]+)>(.*?)<\/\1>/gs;
  let start = 0;
  for (const match of source.matchAll(wrappers)) {
    parts.push({ text: interpolate(source.slice(start, match.index), values, key) });
    parts.push({ text: interpolate(match[2], values, key), wrapper: match[1] });
    start = match.index + match[0].length;
  }
  parts.push({ text: interpolate(source.slice(start), values, key) });
  return parts;
}
