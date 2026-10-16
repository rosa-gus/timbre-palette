import { afterEach, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { locale, localeStore, setLocale } from "../src/i18n/runtime";
import { formatDate, formatLanguage, formatNumber, formatPercent, formatRegisteredDate, formatShareDate, formatWaitDuration } from "../src/i18n/formatters";

const options = { persist: false, updateUrl: false };
afterEach(async () => { vi.unstubAllGlobals(); await setLocale("en-US", options); });

it("formats Portuguese before its UI bundle loads, without selecting it", async () => {
  // This file starts with the static English runtime; no Portuguese UI selection.
  expect(locale).toBe("en-US");
  const fetch = vi.fn(), setItem = vi.fn(), replaceState = vi.fn();
  vi.stubGlobal("fetch", fetch);
  vi.stubGlobal("localStorage", { setItem });
  vi.stubGlobal("window", { history: { replaceState } });
  expect(formatRegisteredDate("2026-10-01T00:00:00Z", "pt-BR")).toBe("out. 2026");
  expect(formatShareDate(new Date(2026, 9, 16, 12), "pt-BR")).toBe("16 DE OUT. 2026");
  expect(formatWaitDuration(120000, "pt-BR")).toBe("2.000 min");
  expect(locale).toBe("en-US");
  expect(get(localeStore)).toBe("en-US");
  expect(fetch).not.toHaveBeenCalled();
  expect(setItem).not.toHaveBeenCalled();
  expect(replaceState).not.toHaveBeenCalled();
});

it.each(["pt-BR", "en-US"] as const)("respects an explicit language while %s is active", async (active) => {
  await setLocale(active, options);
  expect(formatRegisteredDate("2026-01-01T00:00:00Z", "pt-BR")).toBe("jan. 2026");
  expect(formatRegisteredDate("2026-01-01T00:00:00Z", "en-US")).toBe("Jan. 2026");
  expect(formatRegisteredDate("2026-01-01T00:00:00+03:00", "pt-BR")).toBe("dez. 2025");
  expect(formatRegisteredDate("invalid", "en-US")).toBeNull();
  expect(formatShareDate(new Date(2026, 9, 16, 12), "en-US")).toBe("OCT. 16, 2026");
  expect(formatWaitDuration(120000, "en-US")).toBe("2,000 min");
  expect(formatWaitDuration(59, "pt-BR")).toBe("59 s");
  expect(formatWaitDuration(61, "en-US")).toBe("2 min");
  expect(formatNumber(1234.5, undefined, "pt-BR")).toBe("1.234,5");
  expect(formatNumber(1234.5, undefined, "en-US")).toBe("1,234.5");
  expect(formatPercent(0.126, 1, "pt-BR")).toBe("12,6%");
  expect(formatPercent(0.126, 1, "en-US")).toBe("12.6%");
  expect(formatDate(new Date("2026-10-16T00:00:00Z"), "en-US")).toBe("10/16/2026");
  expect(formatLanguage("en-US", "pt-BR")).toMatch(/inglês/);
  expect(locale).toBe(active);
});

it("uses the English formatting message for a missing Portuguese key", async () => {
  const catalog = (await import("../src/i18n/locales/pt-BR/formatting.json")).default;
  const original = catalog.formatting.shareDate;
  try {
    Reflect.deleteProperty(catalog.formatting, "shareDate");
    expect(formatShareDate(new Date(2026, 9, 16, 12), "pt-BR")).toBe("OUT. 16, 2026");
  } finally { catalog.formatting.shareDate = original; }
});
