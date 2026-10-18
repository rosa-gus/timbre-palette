import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initializeLocale, locale, messageParts, t, setLocale } from "../src/i18n/runtime";
import { t as editorialText, setLocale as setEditorialLocale } from "../../editorial/src/i18n/runtime";
import {
  formatDate, formatNumber, formatPercent, formatRegisteredDate,
  formatShareDate, formatWaitDuration,
} from "../src/i18n/formatters";
import { getApiErrorMessage, PaletteApiError } from "../src/api/client";

beforeEach(async () => {
  await setLocale("pt-BR", { persist: false, updateUrl: false });
  await setEditorialLocale("pt-BR", { persist: false, updateUrl: false });
});

afterEach(async () => { await setLocale("pt-BR", { persist: false, updateUrl: false }); vi.unstubAllGlobals(); });

describe("Portuguese presentation compatibility", () => {
  it("keeps public and editorial dictionaries independent", () => {
    expect(t("entry.profileLabel")).toBe("Seu perfil do Last.fm");
    expect(editorialText("sheet.editLabel")).toBe("Editar ficha");
    expect(editorialText("validation.missingReference", { label: "Piano", field: "description" }))
      .toBe("Piano: referência inexistente em description.");
  });

  it("preserves interpolated content without interpreting replacement tokens or markup", () => {
    expect(t("actions.openInstrument", { name: "$& {name} <script>" }))
      .toBe("Abrir ficha de $& {name} <script>");
    expect(t("loading.tracksProgress", { current: 0, total: 4 }))
      .toBe("Carregando faixas (0/4)");
  });

  it("keeps wrappers separate from dynamic values", () => {
    const snapshot = "<version>external</version>";
    const parts = messageParts("sources.snapshot", { snapshot });
    expect(parts.filter((part) => part.wrapper)).toEqual([{ wrapper: "version", text: snapshot }]);
    expect(parts.map((part) => part.text).join(""))
      .toContain(`Usamos o snapshot ${snapshot}, uma cópia desses dados.`);
    expect(() => messageParts("sources.snapshot")).toThrow("Missing message parameter");
  });

  it("renders uppercase markers in text and rich messages without changing external values", () => {
    const registeredLabel = "jan. 2020 <upper>external</upper>";
    const expected = `SCROBBLANDO DESDE ${registeredLabel}`;
    expect(t("profile.registered", { registeredLabel })).toBe(expected);
    const parts = messageParts("profile.registered", { registeredLabel });
    expect(parts.map((part) => part.text).join("")).toBe(expected);
    expect(parts.some((part) => part.wrapper)).toBe(false);
    expect(t("report.dominantPresence", { index: 1 })).toBe("1 / PRESENÇA DOMINANTE");
    expect(t("images.photoCaption", { caption: "João toca piano" })).toBe("FOTO · João toca piano");
    expect(t("sharing.previewIdentity", { listener: "Maria" })).toBe("TIMBRE PALETTE / Maria");
    expect(t("sharing.paletteHeading")).toBe("/ PALETA INSTRUMENTAL");
    expect(editorialText("catalog.heading")).toBe("01 / CATÁLOGO EDITORIAL");
  });

  it("preserves counts, percentages, wait thresholds, and date conventions", () => {
    expect(formatNumber(1234)).toBe("1.234");
    expect(formatPercent(0.126)).toBe("13%");
    expect(formatPercent(0.126, 1)).toBe("12,6%");
    expect(formatPercent(1, 1)).toBe("100%");
    expect(formatWaitDuration(59)).toBe("59 s");
    expect(formatWaitDuration(61)).toBe("2 min");
    expect(formatDate(new Date("2026-10-15T23:00:00-03:00"))).toBe("16/10/2026");
    expect(formatRegisteredDate("2026-01-01T00:00:00+03:00")).toBe("dez. 2025");
    expect(formatRegisteredDate("invalid")).toBeNull();
    expect(formatShareDate(new Date(2026, 9, 15, 12))).toBe("15 DE OUT. 2026");
  });

  it("sets document language and direction without fetching data", async () => {
    const documentElement = { lang: "", dir: "" };
    vi.stubGlobal("document", { documentElement });
    vi.stubGlobal("navigator", { languages: ["pt-BR"] });
    await initializeLocale();
    expect(documentElement).toEqual({ lang: locale, dir: "ltr" });
  });

  it("keeps known API error messages and cancellation behavior", () => {
    expect(getApiErrorMessage(new PaletteApiError("Diagnostic", 422, "invalid_username")))
      .toBe("Informe um perfil válido do Last.fm.");
    expect(getApiErrorMessage(new DOMException("Aborted", "AbortError"))).toBe("");
  });
});
