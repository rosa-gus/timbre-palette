import { locale, type Locale } from "./runtime";
import english from "./locales/en-US/formatting.json";
import portuguese from "./locales/pt-BR/formatting.json";
import { createTranslator } from "./translator";

const catalogs = { "en-US": english, "pt-BR": portuguese };

/** Formatting is synchronous and independent of UI catalog loading or selection. */
const translator = (language: Locale) => createTranslator(catalogs[language], english, language);

export function formatNumber(
  value: number,
  options?: Intl.NumberFormatOptions,
  language = locale,
): string {
  return new Intl.NumberFormat(language, options).format(value);
}

export function formatPercent(
  value: number,
  fractionDigits = 0,
  language = locale,
): string {
  const percent = fractionDigits
    ? Number((value * 100).toFixed(fractionDigits))
    : Math.round(value * 100);
  return `${formatNumber(percent, undefined, language)}%`;
}

export function formatDate(date: Date, language = locale): string {
  return new Intl.DateTimeFormat(language, { timeZone: "UTC" }).format(date);
}

export function formatLanguage(
  language: string,
  displayLocale = locale,
): string {
  return (
    new Intl.DisplayNames([displayLocale], { type: "language" }).of(language) ??
    language
  );
}

const months = [
  "formatting.month1",
  "formatting.month2",
  "formatting.month3",
  "formatting.month4",
  "formatting.month5",
  "formatting.month6",
  "formatting.month7",
  "formatting.month8",
  "formatting.month9",
  "formatting.month10",
  "formatting.month11",
  "formatting.month12",
] as const;

/** Preserve the existing short month/year style and UTC registration dates. */
export function formatRegisteredDate(
  value: string | null | undefined,
  language = locale,
): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return `${translator(language)(months[date.getUTCMonth()])} ${date.getUTCFullYear()}`;
}

/** Share images use the visitor's local date, as before. */
export function formatShareDate(date = new Date(), language = locale): string {
  return translator(language)("formatting.shareDate", {
    day: date.getDate(),
    month: translator(language)(months[date.getMonth()]).toLocaleUpperCase(language),
    year: date.getFullYear(),
  });
}

export function formatWaitDuration(
  seconds: number,
  language = locale,
): string {
  return seconds >= 60
    ? translator(language)("formatting.waitMinutes", { count: formatNumber(Math.ceil(seconds / 60), undefined, language) })
    : translator(language)("formatting.waitSeconds", { count: formatNumber(seconds, undefined, language) });
}
