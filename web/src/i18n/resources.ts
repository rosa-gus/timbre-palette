import { getInstrument, getInstrumentResources } from "../api/client";
import type {
  AnalysisImage,
  InstrumentResource,
  ProfileAnalysisV3,
} from "../api/types";
import { locale, t, type Locale } from "./runtime";

const cache = new Map<
  string,
  { resource: InstrumentResource; expires: number }
>();
type PendingResource = {
  controller: AbortController;
  promise: Promise<InstrumentResource>;
  consumers: number;
  settled: boolean;
};
const pendingResources = new Map<string, PendingResource>();

export async function localizedInstrument(
  slug: string,
  signal: AbortSignal,
  language: Locale = locale,
): Promise<InstrumentResource> {
  signal.throwIfAborted();
  const key = `${language}:${slug}`;
  const saved = cache.get(key);
  if (saved && saved.expires > Date.now()) return saved.resource;
  cache.delete(key);
  let pending = pendingResources.get(key);
  if (!pending) {
    const controller = new AbortController();
    const entry: PendingResource = {
      controller, consumers: 0, settled: false,
      promise: Promise.resolve().then(() => {
        controller.signal.throwIfAborted();
        return getInstrument(slug, controller.signal, language);
      }).then((resource) => {
        controller.signal.throwIfAborted();
        if (pendingResources.get(key) === entry)
          cache.set(key, { resource, expires: Date.now() + 300_000 });
        return resource;
      }).finally(() => {
        entry.settled = true;
        if (pendingResources.get(key) === entry) pendingResources.delete(key);
      }),
    };
    pendingResources.set(key, entry);
    pending = entry;
  }

  const entry = pending;
  entry.consumers++;
  return new Promise<InstrumentResource>((resolve, reject) => {
    let finished = false;
    const finish = (complete: () => void) => {
      if (finished) return;
      finished = true;
      signal.removeEventListener("abort", abort);
      entry.consumers--;
      if (!entry.consumers && !entry.settled) {
        if (pendingResources.get(key) === entry) pendingResources.delete(key);
        entry.controller.abort();
      }
      complete();
    };
    const abort = () => finish(() => reject(signal.reason));
    signal.addEventListener("abort", abort, { once: true });
    entry.promise.then(
      (resource) => finish(() => resolve(resource)),
      (error) => finish(() => reject(error)),
    );
    if (signal.aborted) abort();
  });
}

async function localizedInstruments(
  slugs: string[],
  signal: AbortSignal,
  language: Locale,
  refresh: boolean,
): Promise<Map<string, InstrumentResource>> {
  const missing = slugs.filter((slug) => {
    const key = `${language}:${slug}`;
    if (refresh) cache.delete(key);
    const saved = cache.get(key);
    return !saved || saved.expires <= Date.now();
  });
  const resources = new Map<string, InstrumentResource>();
  for (const slug of slugs) {
    const saved = cache.get(`${language}:${slug}`);
    if (saved && saved.expires > Date.now()) resources.set(slug, saved.resource);
  }
  if (!missing.length) return resources;
  const batch = await getInstrumentResources(missing, signal, language);
  for (const resource of batch.resources) {
    resources.set(resource.slug, resource);
    cache.set(`${language}:${resource.slug}`, {
      resource,
      expires: Date.now() + 300_000,
    });
  }
  return resources;
}

export const LOCALIZATION_DEADLINE_MS = 5_000;
export type LocalizationStatus = "translated" | "fallback" | "missing";
export type LocalizedAnalysis = ProfileAnalysisV3 & {
  localization: {
    incomplete: boolean;
    localeBySlug: Record<string, string | null>;
    statusBySlug: Record<string, LocalizationStatus>;
  };
};

/** Localize display fields without changing analytical facts or cached evidence. */
export async function localizeAnalysis(
  source: ProfileAnalysisV3,
  language: Locale,
  signal: AbortSignal,
  refresh = false,
): Promise<LocalizedAnalysis> {
  signal.throwIfAborted();
  const slugs = new Set(source.track_palette.families.map(({ slug }) => slug));
  const visibleSlugs = new Set(slugs);
  const discoveryVisible =
    source.track_palette.discovery &&
    source.track_palette.analysis.section_availability.discovery === "available";
  if (source.track_palette.discovery) {
    slugs.add(source.track_palette.discovery.instrument_slug);
    if (discoveryVisible)
      visibleSlugs.add(source.track_palette.discovery.instrument_slug);
  }
  const vocabularyVisible =
    source.artist_vocabulary.status === "available" &&
    source.available_views.includes("artist_vocabulary");
  if (vocabularyVisible) {
    for (const family of source.artist_vocabulary.families) {
      slugs.add(family.slug);
      visibleSlugs.add(family.slug);
      family.instruments.forEach(({ slug }) => {
        slugs.add(slug);
        visibleSlugs.add(slug);
      });
    }
  } else {
    for (const family of source.artist_vocabulary.families) {
      slugs.add(family.slug);
      family.instruments.forEach(({ slug }) => slugs.add(slug));
    }
  }
  const resources = await localizedInstruments([...slugs], signal, language, refresh);
  const localeBySlug = Object.fromEntries(
    [...slugs].map((slug) => [slug, resources.get(slug)?.locale ?? null]),
  );
  const statusBySlug = Object.fromEntries(
    [...slugs].map((slug) => {
      const effectiveLocale = resources.get(slug)?.locale;
      return [
        slug,
        !effectiveLocale
          ? "missing"
          : effectiveLocale === language
            ? "translated"
            : "fallback",
      ];
    }),
  ) as Record<string, LocalizationStatus>;
  const name = (slug: string, original: string) =>
    resources.get(slug)?.name ?? original;
  const originalNames = new Map<string, string>();
  for (const family of [
    ...source.track_palette.families,
    ...source.artist_vocabulary.families,
  ])
    originalNames.set(family.name, name(family.slug, family.name));
  for (const family of source.artist_vocabulary.families)
    for (const instrument of family.instruments)
      originalNames.set(
        instrument.name,
        name(instrument.slug, instrument.name),
      );
  const image = (item: AnalysisImage | null): AnalysisImage | null => {
    if (!item) return null;
    return {
      ...item,
      family_name: originalNames.get(item.family_name) ?? item.family_name,
    };
  };
  const discovery = source.track_palette.discovery;
  return {
    ...source,
    localization: {
      incomplete: [...visibleSlugs].some(
        (slug) => statusBySlug[slug] !== "translated",
      ),
      localeBySlug,
      statusBySlug,
    },
    profile: source.is_example
      ? { ...source.profile, realname: t("example.displayName") }
      : source.profile,
    track_palette: {
      ...source.track_palette,
      families: source.track_palette.families.map((family) => ({
        ...family,
        name: name(family.slug, family.name),
        locale: localeBySlug[family.slug] ?? undefined,
        image: image(family.image),
      })),
      discovery: discovery
        ? {
            ...discovery,
            locale: localeBySlug[discovery.instrument_slug] ?? undefined,
            instrument_name: name(
              discovery.instrument_slug,
              discovery.instrument_name,
            ),
            image: image(discovery.image),
          }
        : null,
    },
    artist_vocabulary: {
      ...source.artist_vocabulary,
      families: source.artist_vocabulary.families.map((family) => ({
        ...family,
        name: name(family.slug, family.name),
        locale: localeBySlug[family.slug] ?? undefined,
        instruments: family.instruments.map((instrument) => ({
          ...instrument,
          name: name(instrument.slug, instrument.name),
          locale: localeBySlug[instrument.slug] ?? undefined,
        })),
      })),
      featured_artists: source.artist_vocabulary.featured_artists.map(
        (artist) => ({
          ...artist,
          families: artist.families.map((family) => ({
            ...family,
            name: name(family.slug, family.name),
            locale: localeBySlug[family.slug] ?? undefined,
            instruments: family.instruments.map(
              (instrument) => originalNames.get(instrument) ?? instrument,
            ),
          })),
        }),
      ),
    },
  };
}
