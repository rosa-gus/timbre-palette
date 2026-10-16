import { getInstrument } from "../api/client";
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
export async function localizedInstrument(
  slug: string,
  signal: AbortSignal,
  language: Locale = locale,
): Promise<InstrumentResource> {
  const key = `${language}:${slug}`;
  const saved = cache.get(key);
  if (saved && saved.expires > Date.now()) return saved.resource;
  const resource = await getInstrument(slug, signal, language);
  signal.throwIfAborted();
  cache.set(key, { resource, expires: Date.now() + 300_000 });
  return resource;
}

export const LOCALIZATION_DEADLINE_MS = 5_000;
export type LocalizedAnalysis = ProfileAnalysisV3 & {
  localization: { incomplete: boolean; localeBySlug: Record<string, string> };
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
  if (source.track_palette.discovery)
    slugs.add(source.track_palette.discovery.instrument_slug);
  for (const family of source.artist_vocabulary.families) {
    slugs.add(family.slug);
    family.instruments.forEach(({ slug }) => slugs.add(slug));
  }
  for (const family of source.track_palette.families)
    if (family.image) slugs.add(family.image.depicted_instrument_slug);
  if (source.track_palette.discovery?.image)
    slugs.add(source.track_palette.discovery.image.depicted_instrument_slug);
  const resources = new Map<string, InstrumentResource>();
  const request = new AbortController();
  let closed = false;
  let finish!: () => void;
  const stopped = new Promise<void>((resolve) => { finish = resolve; });
  const stop = () => { closed = true; request.abort(); finish(); };
  signal.addEventListener("abort", stop, { once: true });
  const timer = setTimeout(stop, LOCALIZATION_DEADLINE_MS);
  const pending = [...slugs];
  const work = Promise.all(
    Array.from({ length: Math.min(4, pending.length) }, async () => {
      while (pending.length && !closed) {
        const slug = pending.shift()!;
        try {
          if (refresh) cache.delete(`${language}:${slug}`);
          const resource = await localizedInstrument(slug, request.signal, language);
          if (!closed) resources.set(slug, resource);
        } catch {
          /* Preserve original labels when a resource is unavailable. */
        }
      }
    }),
  );
  try {
    await Promise.race([work, stopped]);
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", stop);
    stop();
  }
  signal.throwIfAborted();
  const localeBySlug = Object.fromEntries([...slugs].map((slug) => [slug, resources.get(slug)?.locale ?? "pt-BR"]));
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
    const resource = resources.get(item.depicted_instrument_slug);
    return {
      ...item,
      locale: resource?.locale ?? "pt-BR",
      depicted_name: name(item.depicted_instrument_slug, item.depicted_name),
      family_name: originalNames.get(item.family_name) ?? item.family_name,
      alt:
        resource?.image?.asset_id === item.asset_id ? resource.image.alt : null,
    };
  };
  const discovery = source.track_palette.discovery;
  return {
    ...source,
    localization: {
      incomplete: [...slugs].some((slug) => !resources.has(slug) || localeBySlug[slug] !== language),
      localeBySlug,
    },
    profile: source.is_example
      ? { ...source.profile, realname: t("example.displayName") }
      : source.profile,
    track_palette: {
      ...source.track_palette,
      families: source.track_palette.families.map((family) => ({
        ...family,
        name: name(family.slug, family.name),
        locale: localeBySlug[family.slug],
        image: image(family.image),
      })),
      discovery: discovery
        ? {
            ...discovery,
            locale: localeBySlug[discovery.instrument_slug],
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
        locale: localeBySlug[family.slug],
        instruments: family.instruments.map((instrument) => ({
          ...instrument,
          name: name(instrument.slug, instrument.name),
          locale: localeBySlug[instrument.slug],
        })),
      })),
      featured_artists: source.artist_vocabulary.featured_artists.map(
        (artist) => ({
          ...artist,
          families: artist.families.map((family) => ({
            ...family,
            name: name(family.slug, family.name),
            locale: localeBySlug[family.slug],
            instruments: family.instruments.map(
              (instrument) => originalNames.get(instrument) ?? instrument,
            ),
          })),
        }),
      ),
    },
  };
}
