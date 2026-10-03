import type {
  AnalysisStatus,
  Confidence,
  FamilyPresence,
  InstrumentImage,
  ListeningPeriod,
  ProfileAnalysisV2,
  ProfileSummary,
  RecordingAnalysis,
  RecordingStatus,
  SectionAvailability,
  SoundBalance,
  Temperament,
  VocabularyFamily,
  VocabularyFeaturedArtist,
} from "../api/types";
import { apiBaseUrl, isProfileAnalysisV2, PaletteApiError } from "../api/client";
import { retryAfterSeconds } from "../api/retry-after";
import { loadHistory, finishHistory, recordHistoryFailure } from "./history";
import {
  boundedText,
  readBoundedJson,
  safeExternalUrl,
  safeHexColor,
  safeLastFmAvatarUrl,
  safeLastFmProfileUrl,
  safeStaticImageUrl,
  sanitizeProfileAnalysis,
} from "../api/input-validation";
const PAGE_SIZE = 50;
const SNAPSHOT_SCHEMA = "musicbrainz-instrument-credits-serving-v2";
const VOCABULARY_METHODOLOGY = "artist-vocabulary-candidate-2";
const METHODOLOGY_VERSION = "0.5.0";
const CONFIDENCE_WEIGHT: Record<Confidence, number> = {
  documented: 1,
  strongly_associated: 0.75,
  estimated: 0.45,
};
const RECORDING_STATUSES: RecordingStatus[] = [
  "resolved",
  "unresolved_identity",
  "pending_enrichment",
  "ambiguous",
  "resolved_without_evidence",
  "transient_failure",
  "terminal_failure",
];
const NATURES = ["acoustic", "electric", "electronic", "sampled", "hybrid"] as const;
type SoundNature = (typeof NATURES)[number];
type ClaimLevel = "instrument" | "family";
type Row = Record<string, unknown>;
type Progress = (
  phase: "tracks" | "profile" | "evidence" | "assembly",
  current: number,
  total: number,
) => void;

interface ListeningTrack {
  title: string;
  artist: string;
  play_count: number;
  mbid: string | null;
  artist_mbid: string | null;
  release_mbid: string | null;
  lastfm_url: string | null;
  layers: InstrumentLayer[];
  recording_status: RecordingStatus;
}

interface InstrumentLayer {
  slug: string;
  name: string;
  family_slug: string;
  family_name: string;
  nature: SoundNature | null;
  role: string;
  confidence: Confidence;
  prominence: number;
  claim_level: ClaimLevel;
}

interface SnapshotInfo {
  snapshot_version: string;
  schema_version: string;
  manifest_hash: string;
  object_prefix: string;
  methodology_version: string;
}

interface VocabularyRow {
  artist_mbid: string;
  instrument_slug: string;
  instrument_name: string;
  family_slug: string;
  family_name: string;
  distinct_recordings: number;
  documented_recordings: number;
  prevalence: number;
  evidence_quality: number;
  source_scope: "recording" | "track";
}

interface EvidenceState {
  snapshot: SnapshotInfo | null;
  aliases: Map<string, string>;
  recordingStatuses: Map<string, string>;
  recordingClaims: Row[];
  artistStatuses: Map<string, string>;
  vocabularyRows: VocabularyRow[];
}

interface ImageCatalog {
  catalog_version: string;
  asset_base_urls?: Row;
  defaults?: Row;
  family_tones?: Row;
  family_names?: Row;
  images?: unknown[];
  instrument_images?: Row;
  family_images?: Row;
  instrument_fallbacks?: Row;
}

interface Metadata {
  username: string;
  profile_url: string | null;
  avatar_url: string | null;
  realname: string | null;
  registered: string | null;
}

interface DiscoveryLayer extends InstrumentLayer {
  tracks: Set<string>;
  artists: Set<string>;
  plays: number;
}

interface TemperamentIdentity {
  title: string;
  invitation: string;
  basis: string;
}

function isRecord(value: unknown): value is Row {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cleanText(value: unknown): string | null {
  return boundedText(value);
}

function finiteNumber(value: unknown, fallback = 0): number {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function round(value: number, places: number): number {
  const scale = 10 ** places;
  return Math.round((value + Number.EPSILON) * scale) / scale;
}

function normalizedName(value: string): string {
  return value.toLocaleLowerCase().trim().replace(/\s+/g, " ");
}

function stringOrder(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function trackKey(track: ListeningTrack): string {
  return `${normalizedName(track.artist)}\u0000${normalizedName(track.title)}\u0000${track.mbid ?? ""}`;
}

function artistKey(track: ListeningTrack): string {
  return normalizedName(track.artist);
}

function validMbid(value: unknown): string | null {
  const text = cleanText(value);
  return text && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(text)
    ? text.toLowerCase()
    : null;
}

function validSlug(value: unknown): string | null {
  const text = boundedText(value, 80);
  return text && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(text) ? text : null;
}

function nonnegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function unitFraction(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;
}

function apiMessage(code: string): string {
  const messages: Record<string, string> = {
    invalid_username: "Informe um perfil válido do Last.fm.",
    invalid_username_or_period: "O perfil ou período informado é inválido.",
    empty_history: "Não foram encontradas faixas nesse período.",
    lastfm_profile_not_found: "Esse perfil não foi encontrado no Last.fm.",
    rate_limited: "Você fez muitas consultas. Aguarde um minuto antes de tentar novamente.",
    lastfm_busy: "As consultas de histórico estão no limite agora. Aguarde um pouco e tente novamente.",
    hydration_busy: "O registro de novas evidências está pausado temporariamente.",
    hydration_daily_budget: "O limite diário de novas evidências foi atingido.",
    d1_daily_budget: "O limite diário de consultas ao catálogo foi atingido. Tente novamente mais tarde.",
    protection_unavailable: "O serviço de análise está temporariamente indisponível. Tente novamente em instantes.",
    lastfm_rate_limited: "O Last.fm está recebendo muitas consultas. Tente novamente em instantes.",
    lastfm_unavailable: "Não foi possível consultar o Last.fm agora.",
    lastfm_key_missing: "A consulta do histórico não está configurada.",
    snapshot_unavailable: "O catálogo de créditos está indisponível agora.",
    unsupported_snapshot_schema: "A versão do catálogo não é compatível com esta análise.",
    invalid_lastfm_response: "O Last.fm devolveu uma resposta inválida.",
    invalid_page_or_limit: "A página solicitada é inválida.",
    request_too_large: "A solicitação excede o tamanho permitido.",
    invalid_mbid_list: "A lista de identidades do catálogo é inválida.",
    invalid_snapshot_version: "A versão do catálogo não é válida.",
    database_unavailable: "O catálogo de evidências está indisponível.",
    hydration_unavailable: "Não foi possível registrar novas evidências agora.",
    example_data_unavailable: "O exemplo do catálogo não está disponível.",
  };
  return messages[code] ?? "Não foi possível montar a análise neste momento.";
}

async function fetchJson(
  url: string,
  signal: AbortSignal,
  init?: RequestInit,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(url, { ...init, signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new PaletteApiError("Não foi possível conectar ao serviço de análise.", 0, "network_error");
  }

  let value: unknown;
  try {
    value = await readBoundedJson(response);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new PaletteApiError("O serviço devolveu uma resposta inválida.", response.status, "invalid_json");
  }
  if (!response.ok) {
    const code = isRecord(value) && typeof value.error === "string"
      ? value.error
      : isRecord(value) && typeof value.code === "string" ? value.code : "api_request_failed";
    throw new PaletteApiError(apiMessage(code), response.status, code, retryAfterSeconds(response));
  }
  if (isRecord(value) && value.error !== undefined) {
    const code = Number(value.error) === 6 ? "lastfm_profile_not_found"
      : Number(value.error) === 29 ? "lastfm_rate_limited"
      : "lastfm_unavailable";
    throw new PaletteApiError(apiMessage(code), 502, code);
  }
  return value;
}

function parseTrack(value: unknown): ListeningTrack | null {
  if (!isRecord(value)) return null;
  const artistData = value.artist;
  const artist = isRecord(artistData) ? boundedText(artistData.name, 256) : boundedText(artistData, 256);
  const title = boundedText(value.name, 512);
  const playCount = Number(value.playcount);
  if (!title || !artist || !Number.isSafeInteger(playCount) || playCount < 0) return null;
  const album = isRecord(value.album) ? value.album : null;
  return {
    title,
    artist,
    play_count: playCount,
    mbid: validMbid(value.mbid),
    artist_mbid: isRecord(artistData) ? validMbid(artistData.mbid) : null,
    release_mbid: album ? validMbid(album.mbid) : null,
    lastfm_url: safeExternalUrl(value.url),
    layers: [],
    recording_status: "pending_enrichment",
  };
}

function parsePage(value: unknown, fallbackUsername: string): {
  username: string;
  tracks: ListeningTrack[];
  totalPages: number | null;
} {
  const topTracks = isRecord(value) && isRecord(value.toptracks) ? value.toptracks : null;
  if (!topTracks) {
    throw new PaletteApiError("O Last.fm devolveu uma resposta inválida.", 502, "invalid_lastfm_response");
  }
  const attributes = isRecord(topTracks["@attr"]) ? topTracks["@attr"] : {};
  const rawTracks = Array.isArray(topTracks.track) ? topTracks.track
    : topTracks.track === undefined ? [] : [topTracks.track];
  if (rawTracks.length > PAGE_SIZE) {
    throw new PaletteApiError("O Last.fm devolveu uma página maior que o permitido.", 502, "invalid_lastfm_response");
  }
  const tracks = rawTracks.map(parseTrack).filter((track): track is ListeningTrack => track !== null);
  const totalPages = Number(attributes.totalPages);
  return {
    username: boundedText(attributes.user, 64) ?? fallbackUsername,
    tracks,
    totalPages: Number.isInteger(totalPages) && totalPages > 0 ? totalPages : null,
  };
}

function parseMetadata(value: unknown, fallbackUsername: string): Metadata {
  const payload = isRecord(value) ? value : {};
  const user = isRecord(payload.profile) ? payload.profile : {};
  const images = Array.isArray(user.image) ? user.image : [user.image];
  const avatar = images.reduce<string | null>((found, candidate) => {
    const raw = isRecord(candidate) ? candidate["#text"] ?? candidate.url : candidate;
    return safeLastFmAvatarUrl(raw) ?? found;
  }, null);
  const registration = isRecord(user.registered) ? user.registered : {};
  let registered: string | null = null;
  const unixTime = Number(registration.unixtime);
  if (Number.isSafeInteger(unixTime) && unixTime >= 0) {
    const date = new Date(unixTime * 1000);
    if (Number.isFinite(date.getTime())) registered = date.toISOString();
  } else {
    const rawDate = cleanText(registration["#text"] ?? registration.text);
    if (rawDate) {
      const parsed = new Date(rawDate);
      if (Number.isFinite(parsed.getTime())) registered = parsed.toISOString();
    }
  }
  const username = boundedText(payload.username, 64) ?? fallbackUsername;
  return {
    username,
    profile_url: safeLastFmProfileUrl(user.url, username),
    avatar_url: avatar,
    realname: boundedText(user.realname, 256),
    registered,
  };
}

function emptyEvidence(): EvidenceState {
  return {
    snapshot: null,
    aliases: new Map(),
    recordingStatuses: new Map(),
    recordingClaims: [],
    artistStatuses: new Map(),
    vocabularyRows: [],
  };
}

function rows(value: unknown): Row[] {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

function mergeEvidence(state: EvidenceState, value: unknown): void {
  if (!isRecord(value)) throw new PaletteApiError("A resposta de evidências é inválida.", 502, "invalid_evidence");
  const snapshot = isRecord(value.snapshot) ? value.snapshot : null;
  if (!snapshot || !["aliases", "recording_statuses", "recording_claims", "artist_statuses", "artist_vocabulary"]
    .every((key) => Array.isArray(value[key]))) {
    throw new PaletteApiError("A resposta de evidências é inválida.", 502, "invalid_evidence");
  }
  {
    const snapshotVersion = boundedText(snapshot.snapshot_version, 128);
    const schemaVersion = cleanText(snapshot.index_schema_version ?? snapshot.schema_version);
    const manifestHash = boundedText(snapshot.manifest_hash, 64);
    if (!snapshotVersion || schemaVersion !== SNAPSHOT_SCHEMA ||
        !manifestHash || !/^[0-9a-f]{64}$/i.test(manifestHash)) {
      throw new PaletteApiError(apiMessage("unsupported_snapshot_schema"), 503, "unsupported_snapshot_schema");
    }
    const nextSnapshot: SnapshotInfo = {
      snapshot_version: snapshotVersion,
      schema_version: schemaVersion,
      manifest_hash: manifestHash,
      object_prefix: boundedText(snapshot.object_prefix, 256) ?? "",
      methodology_version: boundedText(snapshot.methodology_version, 128) ?? VOCABULARY_METHODOLOGY,
    };
    if (state.snapshot && state.snapshot.snapshot_version !== nextSnapshot.snapshot_version) {
      throw new PaletteApiError("O catálogo mudou durante a consulta. Tente novamente.", 503, "snapshot_changed");
    }
    state.snapshot = nextSnapshot;
  }
  for (const row of rows(value.aliases)) {
    const source = validMbid(row.track_mbid);
    const target = validMbid(row.recording_mbid);
    if (source && target) state.aliases.set(source, target);
  }
  for (const row of rows(value.recording_statuses)) {
    const mbid = validMbid(row.recording_mbid);
    const status = row.status;
    if (mbid && ["pending", "complete", "complete_empty", "failed"].includes(status as string)) {
      state.recordingStatuses.set(mbid, status as string);
    }
  }
  for (const row of rows(value.recording_claims)) {
    const recording = validMbid(row.recording_mbid);
    const subject = validSlug(row.subject_slug);
    const family = validSlug(row.family_slug);
    const level = row.claim_level;
    const instrument = row.instrument_slug === null ? null : validSlug(row.instrument_slug);
    if (!recording || !subject || !family || (level !== "instrument" && level !== "family") ||
        (level === "instrument" && instrument !== subject) ||
        (level === "family" && (instrument !== null || subject !== family))) continue;
    state.recordingClaims.push({
      recording_mbid: recording,
      subject_slug: subject,
      family_slug: family,
      claim_level: level,
      instrument_slug: instrument,
      instrument_name: boundedText(row.instrument_name, 256),
      family_name: boundedText(row.family_name, 256),
      sound_nature: NATURES.includes(row.sound_nature as SoundNature) ? row.sound_nature : null,
    });
  }
  for (const row of rows(value.artist_statuses)) {
    const mbid = validMbid(row.artist_mbid);
    const status = row.status;
    if (mbid && ["pending", "complete", "complete_empty", "failed"].includes(status as string)) {
      state.artistStatuses.set(mbid, status as string);
    }
  }
  for (const row of rows(value.artist_vocabulary)) {
    const artist = validMbid(row.artist_mbid);
    const instrument = validSlug(row.instrument_slug);
    const family = validSlug(row.family_slug);
    const instrumentName = boundedText(row.instrument_name, 256);
    const familyName = boundedText(row.family_name, 256);
    const distinctRecordings = nonnegativeInteger(row.distinct_recordings);
    const documentedRecordings = nonnegativeInteger(row.documented_recordings);
    const prevalence = unitFraction(row.prevalence);
    const evidenceQuality = unitFraction(row.evidence_quality);
    if (!artist || !instrument || !family || !instrumentName || !familyName ||
        distinctRecordings === null || documentedRecordings === null ||
        prevalence === null || evidenceQuality === null) continue;
    state.vocabularyRows.push({
      artist_mbid: artist,
      instrument_slug: instrument,
      instrument_name: instrumentName,
      family_slug: family,
      family_name: familyName,
      distinct_recordings: distinctRecordings,
      documented_recordings: documentedRecordings,
      prevalence,
      evidence_quality: evidenceQuality,
      source_scope: row.source_scope === "track" ? "track" : "recording",
    });
  }
}

async function loadImageCatalog(signal: AbortSignal): Promise<ImageCatalog> {
  const empty: ImageCatalog = { catalog_version: "images-0.1.0" };
  try {
    const base = staticAssetBaseUrl();
    const value = await fetchJson(new URL("profile-analysis-catalog.json", base).toString(), signal);
    return isRecord(value) ? value as unknown as ImageCatalog : empty;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return empty;
  }
}

function staticAssetBaseUrl(): URL {
  return new URL(import.meta.env.BASE_URL, window.location.href);
}

function familyTone(catalog: ImageCatalog, familySlug: string): { shadow: string; highlight: string } | null {
  const tones = isRecord(catalog.family_tones) ? catalog.family_tones : {};
  const tone = tones[familySlug];
  if (!isRecord(tone)) return null;
  const shadow = safeHexColor(tone.shadow);
  const highlight = safeHexColor(tone.highlight);
  return shadow && highlight ? { shadow, highlight } : null;
}

function resolveImage(catalog: ImageCatalog, slug: string, familySlug: string | null): InstrumentImage | null {
  const instrumentImages = isRecord(catalog.instrument_images) ? catalog.instrument_images : {};
  const fallbacks = isRecord(catalog.instrument_fallbacks) ? catalog.instrument_fallbacks : {};
  const familyImages = isRecord(catalog.family_images) ? catalog.family_images : {};
  const candidates: { assetId: string; resolution: "exact" | "related" | "family" }[] = [];
  const exact = cleanText(instrumentImages[slug]);
  const related = cleanText(fallbacks[slug]);
  const familyEntry = familySlug ? familyImages[familySlug] : null;
  const familyAsset = isRecord(familyEntry) ? cleanText(familyEntry.asset_id) : null;
  if (exact) candidates.push({ assetId: exact, resolution: "exact" });
  if (related) candidates.push({ assetId: related, resolution: "related" });
  if (familyAsset) candidates.push({ assetId: familyAsset, resolution: "family" });
  const imageItems = Array.isArray(catalog.images) ? catalog.images.filter(isRecord) : [];
  const images = new Map(imageItems.map((item) => [String(item.slug ?? ""), item]));
  const defaults = isRecord(catalog.defaults) ? catalog.defaults : {};
  const names = isRecord(catalog.family_names) ? catalog.family_names : {};
  for (const candidate of candidates) {
    const item = images.get(candidate.assetId);
    const publication = isRecord(item?.publication) ? item.publication : {};
    if (!item || !["approved", "published"].includes(String(publication.status ?? "draft"))) continue;
    const variants = Array.isArray(item.variants) ? item.variants.filter(isRecord) : [];
    if (variants.some((variant) => String(variant.url ?? "").includes("<hash>"))) continue;
    const variant = variants.find((entry) => entry.name === "detail") ?? variants[0];
    const rawUrl = cleanText(variant?.url) ?? cleanText(publication.url) ?? cleanText(item.output);
    if (!rawUrl) continue;
    const url = safeStaticImageUrl(rawUrl);
    if (!url) continue;
    const imageFamily = cleanText(item.family_slug) ?? familySlug ?? "instrumental";
    const depicted = cleanText(item.instrument_slug) ?? cleanText(item.slug) ?? slug;
    const label = cleanText(item.depicted_name) ?? depicted;
    const familyName = cleanText(names[imageFamily]) ?? imageFamily;
    const caption = candidate.resolution === "family"
      ? `Imagem ilustrativa da família ${familyName}: ${label}.`
      : candidate.resolution === "related"
        ? `Imagem relacionada ao instrumento ${label}.`
        : `Imagem do instrumento ${label}.`;
    const treatment = {
      ...defaults,
      ...(familyTone(catalog, imageFamily) ?? {}),
      ...(isRecord(item.treatment) ? item.treatment : {}),
    };
    const tone = {
      shadow: safeHexColor(treatment.shadow) ?? "#000000",
      highlight: safeHexColor(treatment.highlight) ?? "#f29191",
    };
    const rawCredit = isRecord(item.credit) ? item.credit : {};
    return {
      asset_id: candidate.assetId,
      resolution: candidate.resolution,
      depicted_instrument_slug: depicted,
      alt: cleanText(item.alt) ?? `Imagem de ${label}.`,
      caption,
      variants: [{ name: "detail", url, width: finiteNumber(variant?.width), height: finiteNumber(variant?.height) }],
      tone,
      credit: {
        photographer: cleanText(rawCredit.photographer),
        provider: cleanText(rawCredit.provider),
        photo_url: safeExternalUrl(rawCredit.photo_url),
        photographer_url: safeExternalUrl(rawCredit.photographer_url),
        license: cleanText(rawCredit.license),
        license_url: safeExternalUrl(rawCredit.license_url),
      },
    };
  }
  return null;
}

function layersByRecording(state: EvidenceState): Map<string, InstrumentLayer[]> {
  const result = new Map<string, Map<string, InstrumentLayer>>();
  for (const row of state.recordingClaims) {
    const recording = cleanText(row.recording_mbid)?.toLowerCase();
    const subject = cleanText(row.subject_slug);
    const family = cleanText(row.family_slug);
    const claimLevel = row.claim_level;
    const instrumentSlug = cleanText(row.instrument_slug);
    if (!recording || !subject || !family || (claimLevel !== "instrument" && claimLevel !== "family")) continue;
    if (claimLevel === "instrument" && !instrumentSlug) continue;
    const layer: InstrumentLayer = {
      slug: subject,
      name: cleanText(row.instrument_name) ?? cleanText(row.family_name) ?? subject,
      family_slug: family,
      family_name: cleanText(row.family_name) ?? family,
      nature: NATURES.includes(row.sound_nature as SoundNature) ? row.sound_nature as SoundNature : null,
      role: "",
      confidence: "documented",
      prominence: 1,
      claim_level: claimLevel,
    };
    let bySubject = result.get(recording);
    if (!bySubject) result.set(recording, bySubject = new Map());
    bySubject.set(subject, layer);
  }
  return new Map([...result].map(([key, value]) => [key, [...value.values()]]));
}

function enrichTracks(tracks: ListeningTrack[], state: EvidenceState): ListeningTrack[] {
  const claimMap = layersByRecording(state);
  return tracks.map((track) => {
    const source = track.mbid?.toLowerCase() ?? null;
    const canonical = source ? state.aliases.get(source) ?? source : null;
    const layers = canonical ? claimMap.get(canonical) ?? [] : [];
    const status = canonical ? state.recordingStatuses.get(canonical) : undefined;
    const recordingStatus: RecordingStatus = layers.length ? "resolved"
      : !source ? "unresolved_identity"
      : status === "complete" || status === "complete_empty" ? "resolved_without_evidence"
      : status === "failed" ? "terminal_failure"
      : "pending_enrichment";
    return { ...track, layers, recording_status: recordingStatus };
  });
}

function calculateVocalPresence(tracks: ListeningTrack[], totalPlays: number) {
  const vocalTracks = tracks.filter((track) => track.layers.some((layer) =>
    layer.family_slug === "voice" && layer.claim_level === "family" && layer.confidence === "documented"));
  const vocalPlays = vocalTracks.reduce((sum, track) => sum + track.play_count, 0);
  const vocalArtists = new Set(vocalTracks.map(artistKey));
  return {
    documented_tracks: vocalTracks.length,
    documented_artists: vocalArtists.size,
    documented_plays: vocalPlays,
    track_ratio: tracks.length ? round(vocalTracks.length / tracks.length, 4) : 0,
    play_ratio: totalPlays ? round(vocalPlays / totalPlays, 4) : 0,
  };
}

function calculatePalette(tracks: ListeningTrack[], catalog: ImageCatalog): {
  families: FamilyPresence[];
  soundBalance: SoundBalance | null;
  natureScores: Map<SoundNature, number>;
} {
  const familyScores = new Map<string, number>();
  const familyConfidenceScores = new Map<string, number>();
  const familyNames = new Map<string, string>();
  const familyTracks = new Map<string, Set<string>>();
  const natureScores = new Map<SoundNature, number>(NATURES.map((nature) => [nature, 0]));
  let knownNatureScore = 0;
  for (const track of tracks) {
    const layersByFamily = new Map<string, InstrumentLayer[]>();
    for (const layer of track.layers) {
      const layers = layersByFamily.get(layer.family_slug) ?? [];
      layers.push(layer);
      layersByFamily.set(layer.family_slug, layers);
      familyNames.set(layer.family_slug, [familyNames.get(layer.family_slug), layer.family_name]
        .filter((name): name is string => Boolean(name)).sort(stringOrder)[0]);
    }
    const strongest = new Map<string, InstrumentLayer>();
    for (const [family, layers] of layersByFamily) {
      layers.sort((a, b) => {
        const scoreDiff = b.prominence * CONFIDENCE_WEIGHT[b.confidence] - a.prominence * CONFIDENCE_WEIGHT[a.confidence];
        if (scoreDiff) return scoreDiff;
        if (a.claim_level !== b.claim_level) return a.claim_level === "instrument" ? -1 : 1;
        return stringOrder(a.slug, b.slug);
      });
      strongest.set(family, layers[0]);
    }
    const familyWeights = [...strongest].map(([family, layer]) => [family, layer.prominence * CONFIDENCE_WEIGHT[layer.confidence]] as const);
    const totalWeight = familyWeights.reduce((sum, [, weight]) => sum + weight, 0);
    if (totalWeight <= 0) continue;
    const key = trackKey(track);
    for (const [family, weight] of familyWeights) {
      const layer = strongest.get(family)!;
      const score = track.play_count * weight / totalWeight;
      familyScores.set(family, (familyScores.get(family) ?? 0) + score);
      familyConfidenceScores.set(family, (familyConfidenceScores.get(family) ?? 0) + score * CONFIDENCE_WEIGHT[layer.confidence]);
      const set = familyTracks.get(family) ?? new Set<string>();
      set.add(key);
      familyTracks.set(family, set);
      const natureLayers = (layersByFamily.get(family) ?? []).filter((candidate) => candidate.nature !== null);
      const natureWeights = new Map<SoundNature, number>();
      for (const candidate of natureLayers) {
        const nature = candidate.nature!;
        natureWeights.set(nature, (natureWeights.get(nature) ?? 0) + candidate.prominence * CONFIDENCE_WEIGHT[candidate.confidence]);
      }
      const natureWeightTotal = [...natureWeights.values()].reduce((sum, value) => sum + value, 0);
      if (natureWeightTotal <= 0) continue;
      knownNatureScore += score;
      for (const [nature, natureWeight] of natureWeights) {
        natureScores.set(nature, (natureScores.get(nature) ?? 0) + score * natureWeight / natureWeightTotal);
      }
    }
  }
  const totalScore = [...familyScores.values()].reduce((sum, score) => sum + score, 0);
  const sortedSlugs = [...familyScores.keys()].sort((a, b) =>
    (familyScores.get(b)! - familyScores.get(a)!) || stringOrder(a, b));
  const families = sortedSlugs.map((slug): FamilyPresence => {
    const score = familyScores.get(slug)!;
    const confidenceRatio = familyConfidenceScores.get(slug)! / score;
    const confidence: Confidence = confidenceRatio >= 0.9 ? "documented"
      : confidenceRatio >= 0.65 ? "strongly_associated" : "estimated";
    return {
      slug,
      name: familyNames.get(slug) ?? slug,
      share: totalScore ? round(score / totalScore, 4) : 0,
      evidence_count: familyTracks.get(slug)?.size ?? 0,
      confidence,
      image: resolveImage(catalog, slug, slug),
      tone: familyTone(catalog, slug),
    };
  });
  let soundBalance: SoundBalance | null = null;
  if (totalScore > 0 && knownNatureScore / totalScore >= 0.8) {
    const balance = Object.fromEntries(NATURES.map((nature) => [nature, round((natureScores.get(nature) ?? 0) / totalScore, 4)])) as Record<SoundNature, number>;
    soundBalance = {
      acoustic: balance.acoustic,
      electric: balance.electric,
      electronic: balance.electronic,
      sampled: balance.sampled,
      hybrid: balance.hybrid,
      unknown: round(Math.max(0, 1 - NATURES.reduce((sum, nature) => sum + balance[nature], 0)), 4),
    };
  }
  return { families, soundBalance, natureScores };
}

function selectDiscovery(tracks: ListeningTrack[]): DiscoveryLayer | null {
  const candidates = new Map<string, DiscoveryLayer>();
  for (const track of tracks) {
    for (const layer of track.layers) {
      if (layer.claim_level !== "instrument") continue;
      let candidate = candidates.get(layer.slug);
      if (!candidate) {
        candidate = { ...layer, tracks: new Set(), artists: new Set(), plays: 0 };
        candidates.set(layer.slug, candidate);
      } else if (
        layer.prominence * CONFIDENCE_WEIGHT[layer.confidence] > candidate.prominence * CONFIDENCE_WEIGHT[candidate.confidence] ||
        (layer.prominence * CONFIDENCE_WEIGHT[layer.confidence] === candidate.prominence * CONFIDENCE_WEIGHT[candidate.confidence] && layer.role > candidate.role)
      ) {
        Object.assign(candidate, layer);
      }
      candidate.tracks.add(trackKey(track));
      candidate.artists.add(artistKey(track));
      candidate.plays += track.play_count;
    }
  }
  const totalCoveredPlays = tracks.reduce((sum, track) => sum + track.play_count, 0);
  const eligible = [...candidates.values()].filter((candidate) =>
    candidate.tracks.size >= 3 && candidate.artists.size >= 2 &&
    (totalCoveredPlays ? candidate.plays / totalCoveredPlays : 0) <= 0.35);
  eligible.sort((a, b) =>
    ((totalCoveredPlays ? a.plays / totalCoveredPlays : 0) - (totalCoveredPlays ? b.plays / totalCoveredPlays : 0)) ||
    (b.tracks.size - a.tracks.size) || (b.artists.size - a.artists.size) || stringOrder(a.slug, b.slug));
  return eligible[0] ?? null;
}

function buildTemperament(
  families: FamilyPresence[],
  natureScores: Map<SoundNature, number>,
  soundBalance: SoundBalance,
  tracks: ListeningTrack[],
): Temperament {
  const familyShares = new Map(families.map((family) => [family.slug, family.share]));
  const familyTrackSets = new Map<string, Set<string>>();
  for (const family of families) {
    familyTrackSets.set(family.slug, new Set(tracks.filter((track) =>
      track.layers.some((layer) => layer.family_slug === family.slug)).map(trackKey)));
  }
  const familySlugs = [...familyShares.keys()].sort(stringOrder);
  const totalPlays = tracks.reduce((sum, track) => sum + track.play_count, 0) || 1;
  const pairShares = new Map<string, number>();
  for (let i = 0; i < familySlugs.length; i++) {
    for (let j = i + 1; j < familySlugs.length; j++) {
      const first = familySlugs[i];
      const second = familySlugs[j];
      const shared = familyTrackSets.get(first)!;
      const other = familyTrackSets.get(second)!;
      const plays = tracks.filter((track) => shared.has(trackKey(track)) && other.has(trackKey(track)))
        .reduce((sum, track) => sum + track.play_count, 0);
      pairShares.set(`${first}\u0000${second}`, plays / totalPlays);
    }
  }
  const pairShare = (first: string, second: string) => pairShares.get([first, second].sort(stringOrder).join("\u0000")) ?? 0;
  const primaryNature = [...natureScores].sort((a, b) => (b[1] - a[1]) || stringOrder(b[0], a[0]))[0][0];
  const firstFamily = families[0];
  let identity: TemperamentIdentity | null = null;
  const percussion = familyTrackSets.get("percussion") ?? new Set<string>();
  const synthesizers = familyTrackSets.get("synthesizers") ?? new Set<string>();
  let sharedRecordings = 0;
  for (const key of percussion) if (synthesizers.has(key)) sharedRecordings++;
  if (
    (familyShares.get("percussion") ?? 0) >= 0.1 &&
    (familyShares.get("synthesizers") ?? 0) >= 0.1 &&
    sharedRecordings >= 3 && pairShare("percussion", "synthesizers") >= 0.15
  ) {
    identity = {
      title: "Movimento com atmosfera",
      invitation: "Sua escuta encontra impulso sem abrir mão de um lugar para permanecer.",
      basis: "Percussão e sintetizadores aparecem juntos com presença recorrente, aproximando pulso e textura.",
    };
  } else if ((familyShares.get("plucked-strings") ?? 0) >= 0.25 && soundBalance.electric >= 0.25) {
    identity = {
      title: "Corpo elétrico",
      invitation: "Sua escuta tem uma assinatura elétrica: corpo amplificado e possibilidades de timbre.",
      basis: "Cordas dedilhadas e fontes elétricas sustentam a maior parte da paleta.",
    };
  } else if (soundBalance.sampled >= 0.15) {
    identity = {
      title: "Memória em recortes",
      invitation: "Sua escuta encontra identidade nos recortes: sons que carregam outros contextos e ganham novas leituras.",
      basis: "Sons sampleados têm participação recorrente na paleta deste período.",
    };
  } else if (soundBalance.electronic >= 0.25) {
    identity = {
      title: "Textura eletrônica",
      invitation: "Sua escuta encontra nos sons eletrônicos uma linguagem própria, feita de timbres que podem ser moldados e transformados.",
      basis: "Fontes eletrônicas têm a maior participação entre as naturezas identificadas.",
    };
  }
  if (!identity) {
    const fallback: Record<SoundNature, TemperamentIdentity> = {
      acoustic: { title: "Acústica com presença", invitation: "Sua escuta encontra nas fontes acústicas uma marca própria, aproximando gesto, vibração e matéria sonora.", basis: "Fontes acústicas têm a maior participação entre as naturezas identificadas." },
      electric: { title: "Corpo elétrico", invitation: "Sua escuta tem uma assinatura elétrica: uma leitura de corpo amplificado e possibilidades de timbre.", basis: "Fontes elétricas têm a maior participação entre as naturezas identificadas." },
      electronic: { title: "Textura eletrônica", invitation: "Sua escuta encontra nos sons eletrônicos uma linguagem própria, feita de timbres moldados e transformados.", basis: "Fontes eletrônicas têm a maior participação entre as naturezas identificadas." },
      sampled: { title: "Memória em recortes", invitation: "Sua escuta encontra identidade nos recortes: sons que carregam outros contextos e ganham novas leituras.", basis: "Sons sampleados têm participação recorrente na paleta deste período." },
      hybrid: { title: "Orgânica e eletrônica", invitation: "Sua escuta aproxima fontes orgânicas e processos eletrônicos, fazendo da mistura uma marca própria.", basis: "Fontes híbridas têm a maior participação entre as naturezas identificadas." },
    };
    identity = fallback[primaryNature];
  }
  const familyNames = new Map(families.map((family) => [family.slug, family.name]));
  return {
    title: identity.title,
    summary: `${identity.invitation} ${identity.basis} A família com maior participação na paleta é a de ${familyNames.get(firstFamily.slug)!.toLowerCase()}.`,
    disclaimer: "Esta é uma interpretação lúdica do histórico musical, não uma avaliação psicológica ou científica da personalidade.",
  };
}

function sectionAvailability(
  interpretationReady: boolean,
  interpretationCoverageReady: boolean,
  soundBalance: SoundBalance | null,
  discovery: DiscoveryLayer | null,
  temperament: Temperament | null,
): Record<"families" | "sound_balance" | "discovery" | "temperament", SectionAvailability> {
  const failedInterpretation = interpretationCoverageReady ? "insufficient_diversity"
    : !interpretationReady ? "insufficient_coverage" : "no_candidate";
  return {
    families: "available",
    sound_balance: soundBalance ? "available" : "insufficient_nature_evidence",
    discovery: discovery ? "available" : failedInterpretation,
    temperament: temperament ? "available" : failedInterpretation,
  };
}

function analyzePalette(
  tracks: ListeningTrack[],
  profile: ProfileSummary,
  snapshot: SnapshotInfo,
  catalog: ImageCatalog,
  historySource: "lastfm" | "mock" = "lastfm",
): ProfileAnalysisV2["track_palette"] {
  const recordingStatuses = tracks.map((track) => track.recording_status);
  const statusCounts = Object.fromEntries(RECORDING_STATUSES.map((status) => [status, recordingStatuses.filter((value) => value === status).length])) as Record<RecordingStatus, number>;
  const totalTracks = tracks.length;
  const totalPlays = tracks.reduce((sum, track) => sum + track.play_count, 0);
  const covered = tracks.filter((track) => track.layers.length > 0);
  const coveredTracks = covered.length;
  const coveredPlays = covered.reduce((sum, track) => sum + track.play_count, 0);
  const coverageTracks = totalTracks ? round(coveredTracks / totalTracks, 4) : 0;
  const coveragePlays = totalPlays ? round(coveredPlays / totalPlays, 4) : 0;
  const coveredArtists = new Set(covered.map(artistKey));
  const allArtists = new Set(tracks.map(artistKey));
  const minimumTracks = Math.min(totalTracks, Math.max(5, Math.ceil(totalTracks * 0.05)));
  const coverageFloor = coverageTracks >= 0.05 && coveragePlays >= 0.05 && coveredTracks >= minimumTracks;
  const paletteReady = coverageFloor && coveredArtists.size >= Math.min(allArtists.size, 2);
  const interpretationReady = coverageFloor && coveredArtists.size >= Math.min(allArtists.size, 2);
  const status: AnalysisStatus = paletteReady ? "ready" : coveredTracks ? "partial" : "insufficient";
  const vocalPresence = calculateVocalPresence(tracks, totalPlays);
  const sortedTracks = [...tracks].sort((a, b) =>
    stringOrder(artistKey(a), artistKey(b)) ||
    stringOrder(normalizedName(a.title), normalizedName(b.title)) ||
    stringOrder(a.mbid ?? "", b.mbid ?? ""));
  const recordings: RecordingAnalysis[] = sortedTracks.map((track) => ({
    title: track.title,
    artist: track.artist,
    play_count: track.play_count,
    mbid: track.mbid,
    lastfm_url: track.lastfm_url,
    status: track.recording_status,
    status_detail: track.recording_status === "resolved_without_evidence"
      ? "The recording was resolved, but has no accepted instrumental evidence."
      : track.recording_status === "unresolved_identity"
        ? "Last.fm did not provide a MusicBrainz identity for this recording."
        : track.recording_status === "pending_enrichment"
          ? "The recording is awaiting snapshot hydration."
          : track.recording_status === "ambiguous"
            ? "The match is ambiguous and awaiting review."
            : track.recording_status === "transient_failure"
              ? "Snapshot hydration failed transiently and can be retried."
              : track.recording_status === "terminal_failure"
                ? "Snapshot hydration ended without another automatic retry."
                : null,
  }));
  const historyProfile: ProfileSummary = profile;
  const baseNotice = historySource === "mock"
    ? "Este perfil de exemplo combina uma história de escuta fictícia com evidências instrumentais publicadas no catálogo do projeto."
    : "O histórico foi obtido do Last.fm e relacionado às evidências instrumentais publicadas no catálogo do projeto.";
  const notice = status === "insufficient"
    ? `${baseNotice} A cobertura aceita ainda não é suficiente para montar uma paleta.`
    : status === "partial"
      ? `${baseNotice} A paleta usa a evidência publicada até agora; algumas interpretações permanecem restritas e podem ser ampliadas em uma visita futura.`
      : baseNotice;
  const analysisBase = {
    status,
    data_source: "catalog" as const,
    history_source: historySource,
    instrumentation_source: "catalog",
    methodology_version: METHODOLOGY_VERSION,
    catalog_version: snapshot.snapshot_version,
    coverage_tracks: coverageTracks,
    coverage_plays: coveragePlays,
    recording_status_counts: statusCounts,
    notice,
    section_availability: {
      families: "insufficient_coverage" as SectionAvailability,
      sound_balance: "insufficient_coverage" as SectionAvailability,
      discovery: "insufficient_coverage" as SectionAvailability,
      temperament: "insufficient_coverage" as SectionAvailability,
    },
    vocal_presence: vocalPresence,
    image_catalog_version: cleanText(catalog.catalog_version) ?? "images-0.1.0",
  };
  if (!paletteReady && coveredTracks === 0) {
    const reason: SectionAvailability = coverageFloor ? "insufficient_diversity" : "insufficient_coverage";
    return {
      profile: historyProfile,
      analysis: { ...analysisBase, section_availability: { families: reason, sound_balance: reason, discovery: reason, temperament: reason } },
      recordings,
      families: [],
      sound_balance: null,
      discovery: null,
      temperament: null,
    };
  }
  const calculated = calculatePalette(covered, catalog);
  const discoveryLayer = interpretationReady ? selectDiscovery(covered) : null;
  const supportedFamilies = calculated.families.filter((family) => family.evidence_count >= 3);
  const temperamentSupported = supportedFamilies.length >= 2 && supportedFamilies[1].share >= 0.1;
  const temperament = interpretationReady && calculated.soundBalance && temperamentSupported && calculated.natureScores.size
    ? buildTemperament(calculated.families, calculated.natureScores, calculated.soundBalance, covered)
    : null;
  const availability = sectionAvailability(interpretationReady, coverageFloor, calculated.soundBalance, discoveryLayer, temperament);
  return {
    profile: historyProfile,
    analysis: { ...analysisBase, section_availability: availability },
    recordings,
    families: calculated.families,
    sound_balance: calculated.soundBalance,
    discovery: discoveryLayer ? {
      instrument_slug: discoveryLayer.slug,
      title: `Uma presença menos óbvia: ${discoveryLayer.name}`,
      summary: `${discoveryLayer.name} acrescenta uma cor particular à paleta e aparece fora do núcleo instrumental mais evidente.`,
      image: resolveImage(catalog, discoveryLayer.slug, discoveryLayer.family_slug),
    } : null,
    temperament,
  };
}

function uniqueVocabularyRows(rowsToUnique: VocabularyRow[]): VocabularyRow[] {
  const unique = new Map<string, VocabularyRow>();
  for (const row of rowsToUnique) {
    const key = row.instrument_slug;
    const current = unique.get(key);
    if (!current || row.prevalence > current.prevalence) unique.set(key, row);
  }
  return [...unique.values()].sort((a, b) => stringOrder(a.instrument_slug, b.instrument_slug));
}

function analyzeVocabulary(
  tracks: ListeningTrack[],
  snapshot: SnapshotInfo,
  sourceRows: VocabularyRow[],
  pendingArtists: Set<string>,
  catalog: ImageCatalog,
): ProfileAnalysisV2["artist_vocabulary"] {
  const totalTracks = tracks.length;
  const totalPlays = tracks.reduce((sum, track) => sum + track.play_count, 0);
  const artistKeys = new Set(tracks.map((track) => track.artist_mbid?.trim().toLowerCase() || `name:${track.artist.toLocaleLowerCase().trim()}`));
  const unresolvedArtistKeys = new Set(tracks.filter((track) => !track.artist_mbid).map((track) => `name:${track.artist.toLocaleLowerCase().trim()}`));
  const unresolvedTracks = tracks.filter((track) => !track.artist_mbid).length;
  const qualifiedRows = sourceRows.filter((row) => row.distinct_recordings >= 3);
  const byArtistFamily = new Map<string, VocabularyRow[]>();
  for (const row of qualifiedRows) {
    const key = `${row.artist_mbid}\u0000${row.family_slug}`;
    const values = byArtistFamily.get(key) ?? [];
    values.push(row);
    byArtistFamily.set(key, values);
  }
  const qualifiedArtists = new Set([...byArtistFamily.keys()].map((key) => key.split("\u0000", 1)[0]));
  const qualifiedTracks = tracks.filter((track) => track.artist_mbid && qualifiedArtists.has(track.artist_mbid.trim().toLowerCase()));
  const qualifiedTrackCount = qualifiedTracks.length;
  const qualifiedPlayCount = qualifiedTracks.reduce((sum, track) => sum + track.play_count, 0);
  const trackReach = totalTracks ? qualifiedTrackCount / totalTracks : 0;
  const playReach = totalPlays ? qualifiedPlayCount / totalPlays : 0;
  const reach = {
    track_reach: round(trackReach, 4),
    play_reach: round(playReach, 4),
    qualified_artists: qualifiedArtists.size,
    total_artists: artistKeys.size,
    qualified_tracks: qualifiedTrackCount,
    total_tracks: totalTracks,
    qualified_plays: qualifiedPlayCount,
    total_plays: totalPlays,
    unresolved_artists: unresolvedArtistKeys.size,
    unresolved_tracks: unresolvedTracks,
  };
  const artistPlays = new Map<string, number>();
  for (const track of tracks) if (track.artist_mbid) {
    const key = track.artist_mbid.toLowerCase();
    artistPlays.set(key, (artistPlays.get(key) ?? 0) + track.play_count);
  }
  const familyScores = new Map<string, number>();
  const familyRows = new Map<string, VocabularyRow[]>();
  const artistScores = new Map<string, number>();
  const artistFamilyScores = new Map<string, number>();
  for (const [key, familyInstruments] of byArtistFamily) {
    const [artist] = key.split("\u0000");
    const family = key.slice(artist.length + 1);
    const best = [...familyInstruments].sort((a, b) => b.prevalence - a.prevalence)[0];
    const rawWeight = totalPlays ? (artistPlays.get(artist) ?? 0) / totalPlays : 0;
    const contribution = Math.min(rawWeight, 0.4) * best.prevalence * best.evidence_quality;
    familyScores.set(family, (familyScores.get(family) ?? 0) + contribution);
    artistScores.set(artist, (artistScores.get(artist) ?? 0) + contribution);
    artistFamilyScores.set(key, contribution);
    const values = familyRows.get(family) ?? [];
    values.push(...familyInstruments);
    familyRows.set(family, values);
  }
  const totalScore = [...familyScores.values()].reduce((sum, score) => sum + score, 0);
  const concentration = totalScore ? Math.max(...artistScores.values(), 0) / totalScore : 0;
  const vocabularyFamilies: VocabularyFamily[] = [...familyScores.keys()]
    .sort((a, b) => (familyScores.get(b)! - familyScores.get(a)!) || stringOrder(a, b))
    .map((slug) => {
      const rowsForFamily = familyRows.get(slug) ?? [];
      const instruments = uniqueVocabularyRows(rowsForFamily);
      return {
        slug,
        name: instruments[0]?.family_name ?? slug,
        score: round(familyScores.get(slug)!, 6),
        share: totalScore ? round(familyScores.get(slug)! / totalScore, 6) : 0,
        prevalence: round(Math.max(...rowsForFamily.map((row) => row.prevalence), 0), 4),
        supporting_artists: new Set(rowsForFamily.map((row) => row.artist_mbid)).size,
        instruments: instruments.map((row) => ({
          slug: row.instrument_slug,
          name: row.instrument_name,
          distinct_recordings: row.distinct_recordings,
          documented_recordings: row.documented_recordings,
          prevalence: round(row.prevalence, 4),
          evidence: {
            source: "musicbrainz_snapshot" as const,
            scope: row.source_scope,
            snapshot_version: snapshot.snapshot_version,
            quality: round(row.evidence_quality, 4),
            documented_recordings: row.documented_recordings,
          },
        })),
        tone: familyTone(catalog, slug),
      };
    });
  const requiredArtists = Math.min(3, artistKeys.size);
  const gateReason = !qualifiedRows.length ? "no_mapped_evidence"
    : trackReach < 0.1 ? "insufficient_track_reach"
    : playReach < 0.1 ? "insufficient_play_reach"
    : qualifiedArtists.size < requiredArtists ? "insufficient_artist_diversity"
    : concentration > 0.7 ? "excessive_artist_concentration"
    : null;
  let status: "available" | "pending" | "insufficient";
  let reason: string;
  if (gateReason === null) {
    status = "available";
    reason = pendingArtists.size ? "available_with_pending_hydration" : "available";
  } else {
    const potentialArtists = gateReason === "no_mapped_evidence"
      ? new Set(pendingArtists)
      : new Set([...qualifiedArtists, ...pendingArtists]);
    const potentialTracks = tracks.filter((track) => track.artist_mbid && potentialArtists.has(track.artist_mbid.trim().toLowerCase()));
    const potentialTrackReach = totalTracks ? potentialTracks.length / totalTracks : 0;
    const potentialPlayReach = totalPlays ? potentialTracks.reduce((sum, track) => sum + track.play_count, 0) / totalPlays : 0;
    const pendingCouldSatisfy = pendingArtists.size > 0 && potentialTrackReach >= 0.1 && potentialPlayReach >= 0.1 && potentialArtists.size >= requiredArtists;
    status = pendingCouldSatisfy ? "pending" : "insufficient";
    reason = pendingCouldSatisfy ? "snapshot_hydration_pending" : gateReason;
  }
  const featuredArtists: VocabularyFeaturedArtist[] = [];
  if (status === "available") {
    const namesByMbid = new Map<string, string>();
    for (const track of [...tracks].reverse()) if (track.artist_mbid) namesByMbid.set(track.artist_mbid.trim().toLowerCase(), track.artist);
    const ranked = [...qualifiedArtists].sort((a, b) =>
      ((artistScores.get(b) ?? 0) - (artistScores.get(a) ?? 0)) ||
      ((artistPlays.get(b) ?? 0) - (artistPlays.get(a) ?? 0)) || stringOrder(a, b)).slice(0, 3);
    for (const artist of ranked) {
      const artistFamilies = [...byArtistFamily.entries()]
        .filter(([key]) => key.startsWith(`${artist}\u0000`))
        .sort(([keyA], [keyB]) => {
          const slugA = keyA.slice(artist.length + 1);
          const slugB = keyB.slice(artist.length + 1);
          return ((artistFamilyScores.get(keyB) ?? 0) - (artistFamilyScores.get(keyA) ?? 0)) || stringOrder(slugA, slugB);
        })
        .map(([key, familyInstruments]) => {
          const slug = key.slice(artist.length + 1);
          const instruments = uniqueVocabularyRows(familyInstruments).sort((a, b) =>
            (b.prevalence - a.prevalence) || stringOrder(a.instrument_name, b.instrument_name));
          return {
            slug,
            name: familyInstruments[0]?.family_name ?? slug,
            instruments: instruments.map((row) => row.instrument_name),
            tone: familyTone(catalog, slug),
          };
        });
      featuredArtists.push({ mbid: artist, name: namesByMbid.get(artist) ?? artist, families: artistFamilies });
    }
  }
  return {
    status,
    methodology_version: VOCABULARY_METHODOLOGY,
    availability: { status, reason, pending_artists: pendingArtists.size, pending_tracks: 0 },
    reach,
    concentration: round(concentration, 4),
    families: vocabularyFamilies,
    featured_artists: featuredArtists,
    notice: "Recorre em gravações documentadas destes artistas; não descreve necessariamente cada faixa ou a presença de um instrumento no áudio.",
  };
}

function pendingRecordingTargets(
  tracks: ListeningTrack[],
  evidence: EvidenceState,
): { targets: { kind: "track" | "recording"; mbid: string }[]; aliases: number } {
  const targets: { kind: "track" | "recording"; mbid: string }[] = [];
  for (const track of tracks) {
    const source = validMbid(track.mbid);
    if (!source || track.recording_status !== "pending_enrichment") continue;
    const canonical = evidence.aliases.get(source) ?? source;
    const status = evidence.recordingStatuses.get(canonical);
    if (status === "failed") continue;
    const kind = evidence.recordingStatuses.has(canonical) || canonical !== source ? "recording" : "track";
    const mbid = kind === "recording" ? canonical : source;
    if (!targets.some((target) => target.kind === kind && target.mbid === mbid)) targets.push({ kind, mbid });
  }
  const bounded = targets.slice(0, 50);
  return {
    targets: bounded,
    aliases: bounded.filter((target) => target.kind === "track").length,
  };
}

function pendingArtistTargets(tracks: ListeningTrack[], evidence: EvidenceState): string[] {
  const artistIds = [...new Set(tracks.map((track) => validMbid(track.artist_mbid))
    .filter((id): id is string => id !== null))];
  return artistIds.filter((id) => {
    const status = evidence.artistStatuses.get(id);
    return status !== "complete" && status !== "complete_empty" && status !== "failed";
  }).slice(0, 200);
}

function dedupeRows<T>(source: T[], key: (item: T) => string): T[] {
  const output = new Map<string, T>();
  for (const item of source) output.set(key(item), item);
  return [...output.values()];
}

function assemble(
  username: string,
  period: ListeningPeriod,
  rawTracks: ListeningTrack[],
  metadata: Metadata,
  evidence: EvidenceState,
  catalog: ImageCatalog,
  options: { isExample?: boolean; exampleId?: string | null; historySource?: "lastfm" | "mock"; fixtureTracks?: boolean } = {},
): ProfileAnalysisV2 {
  if (!rawTracks.length) throw new PaletteApiError(apiMessage("empty_history"), 422, "empty_history");
  if (!evidence.snapshot) throw new PaletteApiError(apiMessage("snapshot_unavailable"), 503, "snapshot_unavailable");
  const tracks = options.fixtureTracks ? rawTracks : enrichTracks(rawTracks, evidence);
  const totalPlays = tracks.reduce((sum, track) => sum + track.play_count, 0);
  const profile: ProfileSummary = {
    username: metadata.username || username,
    period,
    tracks_analyzed: tracks.length,
    total_plays: totalPlays,
    profile_url: metadata.profile_url,
    avatar_url: metadata.avatar_url,
    realname: metadata.realname,
    registered: metadata.registered,
  };
  const trackPalette = analyzePalette(tracks, profile, evidence.snapshot, catalog, options.historySource);
  const vocabularyRows = dedupeRows(evidence.vocabularyRows, (row) => `${row.artist_mbid}\u0000${row.instrument_slug}`);
  const artistIds = [...new Set(tracks.map((track) => validMbid(track.artist_mbid)).filter((id): id is string => id !== null))];
  const pendingArtists = new Set(options.fixtureTracks ? [] : artistIds.filter((id) => {
    const status = evidence.artistStatuses.get(id);
    return status !== "complete" && status !== "complete_empty" && status !== "failed";
  }));
  const artistVocabulary = analyzeVocabulary(tracks, evidence.snapshot, vocabularyRows, pendingArtists, catalog);
  const paletteAvailable = ["ready", "partial"].includes(trackPalette.analysis.status) &&
    trackPalette.analysis.section_availability.families === "available";
  const vocabularyAvailable = artistVocabulary.status === "available";
  const availableViews: ProfileAnalysisV2["available_views"] = [];
  if (paletteAvailable) availableViews.push("track_palette");
  if (vocabularyAvailable) availableViews.push("artist_vocabulary");
  const defaultView = trackPalette.analysis.status !== "insufficient" && paletteAvailable
    ? "track_palette"
    : trackPalette.analysis.status === "insufficient" && vocabularyAvailable
      ? "artist_vocabulary" : null;
  const recordingTargets = pendingRecordingTargets(tracks, evidence);
  const pendingArtistCount = pendingArtists.size;
  const report: ProfileAnalysisV2 = {
    is_example: options.isExample ?? false,
    example_id: options.isExample ? options.exampleId ?? null : null,
    profile,
    snapshot: evidence.snapshot,
    track_palette: trackPalette,
    artist_vocabulary: artistVocabulary,
    available_views: availableViews,
    default_view: defaultView,
    hydration: {
      status: recordingTargets.targets.length || pendingArtistCount ? "pending" : "complete",
      pending_recordings: recordingTargets.targets.length,
      pending_artists: pendingArtistCount,
      pending_aliases: recordingTargets.aliases,
    },
  };
  if (!isProfileAnalysisV2(report)) {
    throw new PaletteApiError("A montagem no navegador gerou um relatório incompatível com o contrato v2.", 500, "invalid_browser_report");
  }
  return sanitizeProfileAnalysis(report);
}

interface CuratedExampleFixture {
  version: string;
  target_recordings: number;
  max_recordings_per_artist: number;
  period_multipliers: Record<ListeningPeriod, number>;
  vocabulary_snapshot: Row;
  artist_vocabulary: Row[];
  recordings: Row[];
}

function seededRandom(seed: string): () => number {
  let state = 2_166_136_261;
  for (const character of seed) state = Math.imul(state ^ character.charCodeAt(0), 16_777_619);
  if (state === 0) state = 0x6d2b79f5;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4_294_967_296;
  };
}

function shuffle<T>(items: T[], random: () => number): T[] {
  const result = [...items];
  for (let index = result.length - 1; index > 0; index--) {
    const other = Math.floor(random() * (index + 1));
    [result[index], result[other]] = [result[other], result[index]];
  }
  return result;
}

function chooseExampleRecordings(fixture: CuratedExampleFixture, random: () => number): Row[] {
  const direct = shuffle(fixture.recordings.filter((recording) =>
    Array.isArray(recording.layers) && recording.layers.length > 0), random);
  const other = shuffle(fixture.recordings.filter((recording) =>
    !Array.isArray(recording.layers) || recording.layers.length === 0), random);
  const priorityArtists = new Set(fixture.artist_vocabulary
    .filter((row) => finiteNumber(row.distinct_recordings) >= 3)
    .map((row) => cleanText(row.artist_mbid)?.toLowerCase())
    .filter((mbid): mbid is string => Boolean(mbid)));
  const selected: Row[] = [];
  const artistCounts = new Map<string, number>();
  const selectedMbids = new Set<string>();
  const add = (recording: Row): void => {
    const mbid = cleanText(recording.mbid);
    if (!mbid || selectedMbids.has(mbid)) return;
    selected.push(recording);
    selectedMbids.add(mbid);
    const artist = cleanText(recording.artist_mbid)?.toLowerCase()
      ?? `name:${normalizedName(cleanText(recording.artist) ?? "")}`;
    artistCounts.set(artist, (artistCounts.get(artist) ?? 0) + 1);
  };
  for (const recording of [...direct, ...other]) {
    const artist = cleanText(recording.artist_mbid)?.toLowerCase();
    if (artist && priorityArtists.has(artist) && (artistCounts.get(artist) ?? 0) === 0) add(recording);
  }
  const artistLimit = Math.max(1, fixture.max_recordings_per_artist);
  const addCandidates = (candidates: Row[], quota: number): void => {
    const initialCount = selected.length;
    for (const requireNewArtist of [true, false]) {
      for (const recording of candidates) {
        if (selected.length - initialCount >= quota) return;
        const mbid = cleanText(recording.mbid);
        if (!mbid || selectedMbids.has(mbid)) continue;
        const artist = cleanText(recording.artist_mbid)?.toLowerCase()
          ?? `name:${normalizedName(cleanText(recording.artist) ?? "")}`;
        const artistCount = artistCounts.get(artist) ?? 0;
        if (requireNewArtist && artistCount > 0) continue;
        if (artistCount >= artistLimit) continue;
        add(recording);
      }
    }
  };
  const targetCount = Math.max(5, fixture.target_recordings);
  const otherQuota = Math.min(other.length, Math.floor(targetCount / 3));
  addCandidates(direct, targetCount - otherQuota);
  addCandidates(other, targetCount - selected.length);
  addCandidates([...direct, ...other], targetCount - selected.length);
  return selected;
}

function fixtureLayer(value: unknown): InstrumentLayer | null {
  if (!isRecord(value)) return null;
  const slug = cleanText(value.slug);
  const name = cleanText(value.name);
  const familySlug = cleanText(value.family_slug);
  const familyName = cleanText(value.family_name);
  if (!slug || !name || !familySlug || !familyName) return null;
  const rawConfidence = cleanText(value.confidence);
  const confidence: Confidence = rawConfidence === "strongly_associated" || rawConfidence === "estimated"
    ? rawConfidence : "documented";
  const rawNature = cleanText(value.nature);
  return {
    slug,
    name,
    family_slug: familySlug,
    family_name: familyName,
    nature: NATURES.includes(rawNature as SoundNature) ? rawNature as SoundNature : null,
    role: cleanText(value.role) ?? "",
    confidence,
    prominence: finiteNumber(value.prominence, 1),
    claim_level: value.claim_level === "family" ? "family" : "instrument",
  };
}

async function loadExampleFixture(signal: AbortSignal): Promise<CuratedExampleFixture> {
  try {
    const base = staticAssetBaseUrl();
    const value = await fetchJson(new URL("profile-analysis-example.json", base).toString(), signal);
    if (!isRecord(value) || !isRecord(value.vocabulary_snapshot) ||
        !Array.isArray(value.artist_vocabulary) || !Array.isArray(value.recordings) ||
        !isRecord(value.period_multipliers)) throw new Error("Invalid fixture");
    return value as unknown as CuratedExampleFixture;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new PaletteApiError(apiMessage("example_data_unavailable"), 503, "example_data_unavailable");
  }
}

function makeExampleEvidence(fixture: CuratedExampleFixture): EvidenceState {
  const snapshot = fixture.vocabulary_snapshot;
  const state = emptyEvidence();
  state.snapshot = {
    snapshot_version: cleanText(snapshot.snapshot_version) ?? "",
    schema_version: cleanText(snapshot.schema_version) ?? "",
    manifest_hash: cleanText(snapshot.manifest_hash) ?? "",
    object_prefix: cleanText(snapshot.object_prefix) ?? "",
    methodology_version: cleanText(snapshot.methodology_version) ?? VOCABULARY_METHODOLOGY,
  };
  for (const row of fixture.artist_vocabulary) {
    const artist = cleanText(row.artist_mbid)?.toLowerCase();
    const instrument = cleanText(row.instrument_slug);
    const family = cleanText(row.family_slug);
    const instrumentName = cleanText(row.instrument_name);
    const familyName = cleanText(row.family_name);
    if (!artist || !instrument || !family || !instrumentName || !familyName) continue;
    state.vocabularyRows.push({
      artist_mbid: artist,
      instrument_slug: instrument,
      instrument_name: instrumentName,
      family_slug: family,
      family_name: familyName,
      distinct_recordings: finiteNumber(row.distinct_recordings),
      documented_recordings: finiteNumber(row.documented_recordings),
      prevalence: finiteNumber(row.prevalence),
      evidence_quality: finiteNumber(row.evidence_quality),
      source_scope: row.source_scope === "track" ? "track" : "recording",
    });
  }
  return state;
}

export async function getBrowserExampleAnalysis(
  period: ListeningPeriod,
  signal: AbortSignal,
  sampleId = crypto.randomUUID().replaceAll("-", ""),
): Promise<ProfileAnalysisV2> {
  if (!sampleId || sampleId.length > 64) {
    throw new PaletteApiError("O identificador do exemplo é inválido.", 422, "invalid_example_id");
  }
  const [fixture, catalog] = await Promise.all([loadExampleFixture(signal), loadImageCatalog(signal)]);
  const multiplier = finiteNumber(fixture.period_multipliers[period]);
  if (multiplier < 1) throw new PaletteApiError(apiMessage("example_data_unavailable"), 503, "example_data_unavailable");
  const random = seededRandom(`${sampleId}:${period}`);
  const selected = chooseExampleRecordings(fixture, random);
  const qualifiedArtists = new Set(fixture.artist_vocabulary
    .filter((row) => finiteNumber(row.distinct_recordings) >= 3)
    .map((row) => cleanText(row.artist_mbid)?.toLowerCase())
    .filter((mbid): mbid is string => Boolean(mbid)));
  const tracks: ListeningTrack[] = selected.map((recording): ListeningTrack => {
    const artistMbid = validMbid(recording.artist_mbid);
    const layers = Array.isArray(recording.layers)
      ? recording.layers.map(fixtureLayer).filter((layer): layer is InstrumentLayer => layer !== null)
      : [];
    const basePlays = artistMbid && qualifiedArtists.has(artistMbid)
      ? 12 : Math.floor(random() * 11) + 2;
    return {
      title: cleanText(recording.title) ?? "Unknown track",
      artist: cleanText(recording.artist) ?? "Unknown artist",
      play_count: basePlays * multiplier,
      mbid: validMbid(recording.mbid),
      artist_mbid: artistMbid,
      release_mbid: null,
      lastfm_url: null,
      layers,
      recording_status: layers.length ? "resolved" : "resolved_without_evidence",
    };
  }).sort((a, b) => b.play_count - a.play_count || stringOrder(a.mbid ?? "", b.mbid ?? ""));
  if (tracks.length < 5) throw new PaletteApiError(apiMessage("example_data_unavailable"), 503, "example_data_unavailable");
  const artistIds = new Set(tracks.map((track) => track.artist_mbid).filter((id): id is string => id !== null));
  const evidence = makeExampleEvidence(fixture);
  for (const artist of artistIds) evidence.artistStatuses.set(artist, "complete");
  const metadata: Metadata = {
    username: "eu adoro beatles!",
    profile_url: null,
    avatar_url: null,
    realname: "Besouro Hércules",
    registered: null,
  };
  const report = assemble(metadata.username, period, tracks, metadata, evidence, catalog, {
    isExample: true,
    exampleId: sampleId,
    historySource: "mock",
    fixtureTracks: true,
  });
  return report;
}

async function queueHydration(
  baseUrl: string,
  snapshotVersion: string,
  recordingTargets: { kind: "track" | "recording"; mbid: string }[],
  artistMbids: string[],
  signal: AbortSignal,
): Promise<void> {
  if (!recordingTargets.length && !artistMbids.length) return;
  await fetchJson(`${baseUrl}/v3/hydration`, signal, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ snapshot_version: snapshotVersion, recording_targets: recordingTargets, artist_mbids: artistMbids }),
  });
}

export async function getBrowserAnalysis(
  username: string,
  period: ListeningPeriod,
  signal: AbortSignal,
  onProgress: Progress,
  resume = false,
): Promise<ProfileAnalysisV2> {
  const baseUrl = apiBaseUrl();
  const history = await loadHistory(baseUrl, username, period, signal,
    async (page) => parsePage(await fetchJson(
      `${baseUrl}/v3/profiles/${encodeURIComponent(username)}/tracks?period=${encodeURIComponent(period)}&page=${page}&limit=${PAGE_SIZE}`,
      signal,
    ), username),
    async (canonicalUsername) => parseMetadata(await fetchJson(
      `${baseUrl}/v3/profiles/${encodeURIComponent(canonicalUsername)}/metadata`, signal,
    ), canonicalUsername),
    (current, total) => onProgress("tracks", current, total),
    resume,
  );
  const trackPages: ListeningTrack[][] = history.pages.map((page) => page.tracks.map((track) => ({
    ...track, layers: [], recording_status: "pending_enrichment",
  })));
  const rawTracks = trackPages.flat();
  onProgress("profile", 1, 1);
  const metadata = history.metadata ?? { username: history.username, profile_url: null, avatar_url: null, realname: null, registered: null };
  const canonicalUsername = metadata.username || history.username;
  try {
    const evidence = emptyEvidence();
    for (let index = 0; index < trackPages.length; index++) {
      const pageTracks = trackPages[index];
      const trackMbids = [...new Set(pageTracks.map((track) => validMbid(track.mbid)).filter((mbid): mbid is string => mbid !== null))];
      const artistMbids = [...new Set(pageTracks.map((track) => validMbid(track.artist_mbid)).filter((mbid): mbid is string => mbid !== null))];
      onProgress("evidence", index + 1, trackPages.length);
      if (!trackMbids.length && !artistMbids.length && evidence.snapshot) continue;
      const payload = await fetchJson(`${baseUrl}/v3/evidence`, signal, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          track_mbids: trackMbids,
          artist_mbids: artistMbids,
          ...(evidence.snapshot ? { snapshot_version: evidence.snapshot.snapshot_version } : {}),
        }),
      });
      mergeEvidence(evidence, payload);
    }
    onProgress("assembly", 1, 1);
    const catalog = await loadImageCatalog(signal);
    const report = assemble(canonicalUsername, period, rawTracks, metadata, evidence, catalog);
    const enrichedTracks = enrichTracks(rawTracks, evidence);
    const recordingTargets = pendingRecordingTargets(enrichedTracks, evidence).targets;
    const artistTargets = pendingArtistTargets(enrichedTracks, evidence);
    try {
      await queueHydration(baseUrl, evidence.snapshot!.snapshot_version, recordingTargets, artistTargets, signal);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      // The report is still valid when the background queue is temporarily unavailable.
    }
    signal.throwIfAborted();
    finishHistory(history.id);
    return report;
  } catch (error) {
    if (!signal.aborted) recordHistoryFailure(history.id, error);
    throw error;
  }
}
