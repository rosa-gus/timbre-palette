import { locale, setLocale } from "../src/i18n/runtime";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { PaletteReport, Temperament } from "../src/api/types";
import { getAnalysisNotice, getDiscoveryCopy, getImageCopy, getPortraitCopy } from "../src/analysis/presentation";
import { getAnalysis, getApiErrorMessage, PaletteApiError } from "../src/api/client";

const report: PaletteReport = {
  profile: { username: "listener", period: "1month", tracks_analyzed: 10, total_plays: 100 },
  analysis: {
    status: "ready", data_source: "catalog", history_source: "lastfm", instrumentation_source: "catalog",
    methodology_version: "0.5.0", catalog_version: "test", image_catalog_version: "test",
    coverage_tracks: 1, coverage_plays: 1,
    recording_status_counts: { resolved: 10, unresolved_identity: 0, pending_enrichment: 0, ambiguous: 0,
      resolved_without_evidence: 0, transient_failure: 0, terminal_failure: 0 },
    vocal_presence: { documented_tracks: 0, documented_artists: 0, documented_plays: 0, track_ratio: 0, play_ratio: 0 },
    section_availability: { families: "available", discovery: "no_candidate", sound_balance: "available", temperament: "available" },
  },
  recordings: [], sound_balance: null, discovery: null,
  families: [
    { slug: "percussion", name: "Percussão", share: 0.6, evidence_count: 6, confidence: "documented", image: null, tone: null },
    { slug: "synthesizers", name: "Sintetizadores", share: 0.4, evidence_count: 4, confidence: "documented", image: null, tone: null },
  ],
  temperament: { rule: "recurring-percussion-synthesizers", primary_family_slug: "percussion", primary_nature: "electronic" },
};

beforeEach(() => setLocale("pt-BR", { persist: false, updateUrl: false }));
afterEach(() => vi.unstubAllGlobals());

it("renders the selected rule without recalculation, mutation, or network calls", () => {
  const source = JSON.stringify(report);
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const copy = getPortraitCopy(report);
  expect(copy.title).toBe("Movimento com atmosfera");
  expect(copy.summary).toBe("Sua escuta encontra impulso sem abrir mão de um lugar para permanecer. Percussão e sintetizadores aparecem juntos com presença recorrente, aproximando pulso e textura. A família com maior participação na paleta é a de percussão.");
  expect(copy.disclaimer).toContain("não uma avaliação psicológica ou científica");
  expect(getPortraitCopy(JSON.parse(source))).toEqual(copy);
  expect(JSON.stringify(report)).toBe(source);
  expect(fetch).not.toHaveBeenCalled();
});

it.each([
  ["electric-plucked-strings", "Corpo elétrico", "Cordas dedilhadas"],
  ["dominant-electric", "Corpo elétrico", "Fontes elétricas"],
  ["recurring-electronic", "Textura eletrônica", "podem ser moldados"],
  ["dominant-electronic", "Textura eletrônica", "timbres moldados"],
  ["recurring-sampled", "Memória em recortes", "Sons sampleados"],
  ["dominant-sampled", "Memória em recortes", "Sons sampleados"],
  ["dominant-acoustic", "Acústica com presença", "Fontes acústicas"],
  ["dominant-hybrid", "Orgânica e eletrônica", "Fontes híbridas"],
] as const)("keeps distinct wording for %s", (rule: Temperament["rule"], title, phrase) => {
  const copy = getPortraitCopy({ ...report, temperament: { ...report.temperament!, rule } });
  expect(copy.title).toBe(title);
  expect(copy.summary).toContain(phrase);
});

it("uses evidence summaries instead of inventing a temperament when unavailable", () => {
  const partial = { ...report, temperament: null };
  expect(getPortraitCopy(partial).title).toBe("Percussão e Sintetizadores.");
  expect(getPortraitCopy({ ...partial, families: partial.families.slice(0, 1) }).title).toBe("Um primeiro retrato: percussão.");
  expect(getPortraitCopy({ ...partial, families: [] }).title).toBe("Sua escuta ainda não ganhou uma paleta.");
});

it("renders notices, discovery and generated image text from facts", () => {
  expect(getAnalysisNotice({ ...report.analysis, status: "insufficient" })).toContain("A cobertura aceita ainda não é suficiente");
  expect(getAnalysisNotice({ ...report.analysis, status: "partial", history_source: "mock" })).toContain("Este perfil de exemplo");
  expect(getDiscoveryCopy({ instrument_slug: "cuica", instrument_name: "Cuíca", image: null }).title)
    .toBe("Uma presença menos óbvia: Cuíca");
  const image = {
    asset_id: "cuica", resolution: "family" as const, depicted_instrument_slug: "cuica",
    depicted_name: "Cuíca", family_name: "Percussão", alt: null, variants: [],
    tone: { shadow: "#000000", highlight: "#f29191" },
    credit: { photographer: null, provider: null, photo_url: null, photographer_url: null, license: null, license_url: null },
  };
  expect(getImageCopy(image)).toMatchObject({ alt: "Imagem de Cuíca.", caption: "Imagem ilustrativa da família Percussão: Cuíca." });
  expect(getImageCopy({ ...image, alt: "Reviewed description" }).alt).toBe("Reviewed description");
});

it("rejects legacy server reports on the versioned route without parsing prose or retrying v2", async () => {
  const fetch = vi.fn(async (_input: RequestInfo | URL) => Response.json({ track_palette: { temperament: { title: "Legacy title" } } }));
  vi.stubGlobal("fetch", fetch);
  await expect(getAnalysis("listener", "1month", new AbortController().signal)).rejects.toMatchObject({ code: "invalid_report" });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toContain("/v3/profiles/listener/analysis?period=1month");
  expect(getApiErrorMessage(new PaletteApiError("Untrusted provider message", 500, "future_error")))
    .toBe("Não foi possível concluir a análise.");
});


it.each(["pt-BR", "en-US"] as const)("keeps explicit narrative languages independent of the active %s UI", async (active) => {
  await setLocale(active, { persist: false, updateUrl: false });
  const source = JSON.stringify(report);
  expect(getPortraitCopy(report, "en-US").title).toBe("Movement with atmosphere");
  expect(getPortraitCopy(report, "pt-BR").title).toBe("Movimento com atmosfera");
  expect(getAnalysisNotice(report.analysis, "en-US")).toContain("The history was obtained");
  expect(getAnalysisNotice(report.analysis, "pt-BR")).toContain("O histórico foi obtido");
  const discovery = { instrument_slug: "cuica", instrument_name: "Cuíca", image: null };
  expect(getDiscoveryCopy(discovery, "en-US").title).toBe("A less obvious presence: Cuíca");
  expect(getDiscoveryCopy(discovery, "pt-BR").title).toBe("Uma presença menos óbvia: Cuíca");
  const image = {
    asset_id: "cuica", resolution: "exact" as const, depicted_instrument_slug: "cuica",
    depicted_name: "Cuíca", family_name: "Percussão", alt: null, variants: [],
    tone: { shadow: "#000000", highlight: "#f29191" },
    credit: { photographer: null, provider: null, photo_url: null, photographer_url: null, license: null, license_url: null },
  };
  expect(getImageCopy(image, "en-US").alt).toBe("Image of Cuíca.");
  expect(getImageCopy(image, "pt-BR").alt).toBe("Imagem de Cuíca.");
  expect(getImageCopy({ ...image, alt: "Reviewed alt" }, "pt-BR").alt).toBe("Reviewed alt");
  expect(JSON.stringify(report)).toBe(source);
  expect(locale).toBe(active);
});
