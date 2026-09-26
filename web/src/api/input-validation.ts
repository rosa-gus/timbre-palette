import type {
  InstrumentImage,
  InstrumentResource,
  ProfileAnalysisV2,
} from "./types";

const MAX_RESPONSE_BYTES = 2_000_000;
const MAX_JSON_NODES = 20_000;
const MAX_JSON_DEPTH = 16;
const MAX_ARRAY_LENGTH = 500;
const MAX_JSON_STRING_LENGTH = 4_096;
const MAX_URL_LENGTH = 2_048;
const HEX_COLOR = /^#[0-9a-f]{6}$/i;
const LASTFM_IMAGE_HOSTS = new Set([
  "lastfm-img.freetls.fastly.net",
  "lastfm.freetls.fastly.net",
  "lastfm-img2.akamaized.net",
]);

export function boundedText(value: unknown, maxLength = 512): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text && text.length <= maxLength && !text.includes("\u0000") ? text : null;
}

export function safeHexColor(value: unknown): string | null {
  return typeof value === "string" && HEX_COLOR.test(value) ? value : null;
}

function httpUrl(value: unknown): URL | null {
  const text = boundedText(value, MAX_URL_LENGTH);
  if (!text) return null;
  try {
    const url = new URL(text);
    return (url.protocol === "https:" || url.protocol === "http:") &&
      !url.username && !url.password ? url : null;
  } catch {
    return null;
  }
}

export function safeExternalUrl(value: unknown): string | null {
  return httpUrl(value)?.toString() ?? null;
}

export function safeLastFmProfileUrl(value: unknown, username: string): string | null {
  const name = boundedText(username, 64);
  if (!name) return null;
  const fallback = `https://www.last.fm/user/${encodeURIComponent(name)}`;
  const url = httpUrl(value);
  if (!url || url.protocol !== "https:" ||
      (url.hostname !== "www.last.fm" && url.hostname !== "last.fm")) return fallback;
  const parts = url.pathname.split("/").filter(Boolean);
  try {
    if (parts[0]?.toLowerCase() !== "user" ||
        decodeURIComponent(parts[1] ?? "").toLowerCase() !== name.toLowerCase()) return fallback;
  } catch {
    return fallback;
  }
  return url.toString();
}

export function safeLastFmAvatarUrl(value: unknown): string | null {
  const url = httpUrl(value);
  return url?.protocol === "https:" && LASTFM_IMAGE_HOSTS.has(url.hostname) &&
    url.pathname.startsWith("/i/u/") ? url.toString() : null;
}

function assetBaseUrl(): URL {
  return new URL(import.meta.env.BASE_URL, window.location.href);
}

export function safeStaticImageUrl(value: unknown): string | null {
  const raw = boundedText(value, MAX_URL_LENGTH);
  if (!raw) return null;
  const base = assetBaseUrl();
  try {
    const url = new URL(raw, base);
    const prefix = new URL("instruments/", base);
    return url.origin === base.origin && url.pathname.startsWith(prefix.pathname) &&
      (url.protocol === "https:" || url.protocol === "http:") &&
      !url.username && !url.password ? url.toString() : null;
  } catch {
    return null;
  }
}

function safePublishedImageUrl(value: unknown): string | null {
  const url = httpUrl(value);
  if (!url) return null;
  const app = assetBaseUrl();
  const localPrefix = new URL("instruments/", app);
  const officialPrefix = "/timbre-palette/instruments/";
  return (url.origin === app.origin && url.pathname.startsWith(localPrefix.pathname)) ||
    (url.origin === "https://rosa-gus.github.io" && url.pathname.startsWith(officialPrefix))
    ? url.toString() : null;
}

function safeTone(value: unknown): { shadow: string; highlight: string } | null {
  if (!isRecord(value)) return null;
  const shadow = safeHexColor(value.shadow);
  const highlight = safeHexColor(value.highlight);
  return shadow && highlight ? { shadow, highlight } : null;
}

function safeImage(value: InstrumentImage | null): InstrumentImage | null {
  if (!isRecord(value) || !Array.isArray(value.variants) || !isRecord(value.credit)) return null;
  const assetId = boundedText(value.asset_id, 128);
  const depictedSlug = boundedText(value.depicted_instrument_slug, 80);
  const alt = boundedText(value.alt, 512);
  const caption = boundedText(value.caption, 512);
  const resolution = value.resolution;
  if (!assetId || !depictedSlug || !alt || !caption ||
      (resolution !== "exact" && resolution !== "related" && resolution !== "family")) return null;
  const variants = value.variants.flatMap((variant) => {
    if (!isRecord(variant)) return [];
    const url = safePublishedImageUrl(variant.url);
    return url && Number.isSafeInteger(variant.width) && variant.width > 0 &&
      Number.isSafeInteger(variant.height) && variant.height > 0
      ? [{ name: "detail" as const, url, width: variant.width, height: variant.height }]
      : [];
  }).slice(0, 3);
  if (!variants.length) return null;
  return {
    asset_id: assetId,
    resolution,
    depicted_instrument_slug: depictedSlug,
    alt,
    caption,
    variants,
    tone: safeTone(value.tone) ?? { shadow: "#000000", highlight: "#F29191" },
    credit: {
      photographer: boundedText(value.credit.photographer, 256),
      provider: boundedText(value.credit.provider, 256),
      photo_url: safeExternalUrl(value.credit.photo_url),
      photographer_url: safeExternalUrl(value.credit.photographer_url),
      license: boundedText(value.credit.license, 256),
      license_url: safeExternalUrl(value.credit.license_url),
    },
  };
}

export function sanitizeProfileAnalysis(report: ProfileAnalysisV2): ProfileAnalysisV2 {
  const profile = {
    ...report.profile,
    profile_url: report.is_example ? null : safeLastFmProfileUrl(report.profile.profile_url, report.profile.username),
    avatar_url: safeLastFmAvatarUrl(report.profile.avatar_url),
  };
  return {
    ...report,
    profile,
    track_palette: {
      ...report.track_palette,
      profile,
      recordings: report.track_palette.recordings.map((recording) => ({
        ...recording,
        lastfm_url: safeExternalUrl(recording.lastfm_url),
      })),
      families: report.track_palette.families.map((family) => ({
        ...family,
        tone: safeTone(family.tone),
        image: safeImage(family.image),
      })),
      discovery: report.track_palette.discovery ? {
        ...report.track_palette.discovery,
        image: safeImage(report.track_palette.discovery.image),
      } : null,
    },
    artist_vocabulary: {
      ...report.artist_vocabulary,
      families: report.artist_vocabulary.families.map((family) => ({
        ...family,
        tone: safeTone(family.tone),
      })),
      featured_artists: report.artist_vocabulary.featured_artists.map((artist) => ({
        ...artist,
        families: artist.families.map((family) => ({ ...family, tone: safeTone(family.tone) })),
      })),
    },
  };
}

export function sanitizeInstrumentResource(resource: InstrumentResource): InstrumentResource {
  return {
    ...resource,
    tone: safeTone(resource.tone),
    image: safeImage(resource.image),
    sources: resource.sources.filter(isRecord).map((source) => ({
      ...source,
      url: safeExternalUrl(source.url),
    })) as InstrumentResource["sources"],
    further_reading: (resource.further_reading ?? []).filter(isRecord).flatMap((article) => {
      const url = safeExternalUrl(article.url);
      return url && boundedText(article.title) ? [{ ...article, url }] : [];
    }) as InstrumentResource["further_reading"],
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isBoundedJson(value: unknown): boolean {
  const stack: { value: unknown; depth: number }[] = [{ value, depth: 0 }];
  let nodes = 0;
  while (stack.length) {
    const current = stack.pop()!;
    if (++nodes > MAX_JSON_NODES || current.depth > MAX_JSON_DEPTH) return false;
    if (typeof current.value === "string") {
      if (current.value.length > MAX_JSON_STRING_LENGTH) return false;
    } else if (Array.isArray(current.value)) {
      if (current.value.length > MAX_ARRAY_LENGTH) return false;
      for (const item of current.value) stack.push({ value: item, depth: current.depth + 1 });
    } else if (isRecord(current.value)) {
      const entries = Object.entries(current.value);
      if (entries.length > MAX_ARRAY_LENGTH || entries.some(([key]) => key.length > 128)) return false;
      for (const [, item] of entries) stack.push({ value: item, depth: current.depth + 1 });
    }
  }
  return true;
}

export async function readBoundedJson(response: Response): Promise<unknown> {
  const declaredLength = Number(response.headers.get("Content-Length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
    throw new Error("response_too_large");
  }
  if (!response.body) throw new Error("invalid_json");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_RESPONSE_BYTES) {
      await reader.cancel();
      throw new Error("response_too_large");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  const payload: unknown = JSON.parse(new TextDecoder().decode(bytes));
  if (!isBoundedJson(payload)) throw new Error("invalid_response_shape");
  return payload;
}
