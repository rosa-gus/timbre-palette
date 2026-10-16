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
  const values = args[0] as Record<string, string | number> | undefined;
  return messages[key].replace(/\{([^{}]+)\}/g, (_, name: string) => {
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
