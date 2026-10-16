import { locale, t } from "./runtime";

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
  "dates.month1",
  "dates.month2",
  "dates.month3",
  "dates.month4",
  "dates.month5",
  "dates.month6",
  "dates.month7",
  "dates.month8",
  "dates.month9",
  "dates.month10",
  "dates.month11",
  "dates.month12",
] as const;

/** Preserve the existing short month/year style and UTC registration dates. */
export function formatRegisteredDate(
  value: string | null | undefined,
  _language = locale,
): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return `${t(months[date.getUTCMonth()])} ${date.getUTCFullYear()}`;
}

/** Share images use the visitor's local date, as before. */
export function formatShareDate(date = new Date()): string {
  return t("sharing.date", {
    day: date.getDate(),
    month: t(months[date.getMonth()]).toLocaleUpperCase(locale),
    year: date.getFullYear(),
  });
}

export function formatWaitDuration(
  seconds: number,
  _language = locale,
): string {
  return seconds >= 60
    ? t("history.minutes", { count: Math.ceil(seconds / 60) })
    : t("history.seconds", { count: seconds });
}
