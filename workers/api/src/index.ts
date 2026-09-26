import { catalogStats, getInstrument, openApiDocument } from "./catalog";
import { API_VERSION } from "./version";

const LASTFM_URL = "https://ws.audioscrobbler.com/2.0/";
const SNAPSHOT_SCHEMA_VERSION = "musicbrainz-instrument-credits-serving-v2";
const PERIODS = new Set([
  "7day",
  "1month",
  "3month",
  "6month",
  "12month",
  "overall",
]);
const MBID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const JSON_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Accept, Content-Type",
};
const ERROR_MESSAGES: Record<string, string> = {
  method_not_allowed: "This HTTP method is not supported for this endpoint.",
  not_found: "The requested resource was not found.",
  invalid_username: "The Last.fm username is invalid.",
  invalid_username_or_period: "The username or listening period is invalid.",
  invalid_page_or_limit: "The page or page size is invalid.",
  lastfm_key_missing: "The Last.fm API key is not configured.",
  lastfm_unavailable: "Last.fm is temporarily unavailable.",
  lastfm_profile_not_found: "The Last.fm profile was not found.",
  lastfm_rate_limited: "Last.fm is rate limiting requests.",
  invalid_lastfm_response: "Last.fm returned an invalid response.",
  database_unavailable: "The evidence database is unavailable.",
  request_too_large: "The request body exceeds the allowed size.",
  invalid_json: "The request body is not valid JSON.",
  invalid_body: "The request body is invalid.",
  invalid_mbid_list: "The MBID list is invalid.",
  invalid_snapshot_version: "The snapshot version is invalid.",
  snapshot_unavailable: "The requested evidence snapshot is unavailable.",
  unsupported_snapshot_schema: "The evidence snapshot schema is not supported.",
  d1_query_failed: "An evidence database query failed.",
  api_unavailable: "The API could not complete the request.",
  invalid_hydration_request:
    "The hydration request is invalid or exceeds its limits.",
  invalid_hydration_target: "A recording hydration target is invalid.",
  invalid_artist_mbid: "An artist MBID is invalid.",
  hydration_unavailable: "The hydration request could not be stored.",
};

type Row = Record<string, unknown>;
type Track = {
  title: string;
  artist: string;
  play_count: number;
  mbid: string | null;
  artist_mbid: string | null;
  release_mbid: string | null;
  lastfm_url: string | null;
};

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: JSON_HEADERS });
    }
    if (request.method === "POST" && url.pathname === "/v3/evidence") {
      return profileEvidence(request, env);
    }
    if (request.method === "POST" && url.pathname === "/v3/hydration") {
      return scheduleHydration(request, env);
    }
    if (request.method === "GET" && url.pathname === "/health") {
      return json({
        status: "ok",
        service: "timbre-palette-api",
        version: API_VERSION,
      });
    }
    if (request.method === "GET" && url.pathname === "/v2/catalog/stats") {
      return catalogStats(env);
    }
    const instrumentMatch = /^\/v2\/instruments\/([^/]+)$/.exec(url.pathname);
    if (request.method === "GET" && instrumentMatch) {
      return getInstrument(url, env, instrumentMatch[1]);
    }
    if (request.method === "GET" && url.pathname === "/openapi.json")
      return openApiDocument();
    if (request.method !== "GET") return failure("method_not_allowed", 405);

    const tracksMatch = /^\/v3\/profiles\/([^/]+)\/tracks$/.exec(url.pathname);
    if (tracksMatch) return profileTracks(url, env, tracksMatch[1]);

    const match = /^\/v3\/profiles\/([^/]+)\/metadata$/.exec(url.pathname);
    if (!match) return failure("not_found", 404);

    let username: string;
    try {
      username = decodeURIComponent(match[1]).trim();
    } catch {
      return failure("invalid_username", 422);
    }
    if (!username || username.length > 64)
      return failure("invalid_username", 422);
    if (!env.LASTFM_API_KEY) return failure("lastfm_key_missing", 503);

    const started = performance.now();
    try {
      const info = await lastFm(env.LASTFM_API_KEY, "user.getinfo", username);
      const profile = record(info.user);
      if (!profile) throw new ApiError("invalid_lastfm_response", 502);
      const wallMs = Math.round(performance.now() - started);
      console.log({ event: "profile_metadata", wall_ms: wallMs });
      return json({
        username: text(profile.name) ?? username,
        profile,
        wall_ms: wallMs,
      });
    } catch (error) {
      const code =
        error instanceof ApiError ? error.code : "lastfm_unavailable";
      const status = error instanceof ApiError ? error.status : 502;
      console.error({ event: "profile_metadata_failed", code });
      return failure(code, status);
    }
  },
};

class ApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
  ) {
    super(code);
  }
}

async function lastFm(
  key: string,
  method: string,
  username: string,
  period?: string,
  limit = 200,
  page = 1,
): Promise<Row> {
  const url = lastFmUrl(key, method, username, period, limit, page);
  let response: Response;
  try {
    response = await fetch(url, {
      headers: {
        Accept: "application/json",
        "User-Agent": `timbre-palette/${API_VERSION}`,
      },
    });
  } catch {
    throw new ApiError("lastfm_unavailable", 502);
  }
  if (!response.ok) throw new ApiError("lastfm_unavailable", 502);
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("invalid_lastfm_response", 502);
  }
  const data = record(payload);
  if (!data) throw new ApiError("invalid_lastfm_response", 502);
  if (data.error !== undefined) {
    const code = Number(data.error);
    if (code === 6) throw new ApiError("lastfm_profile_not_found", 404);
    if (code === 29) throw new ApiError("lastfm_rate_limited", 503);
    throw new ApiError("lastfm_unavailable", 502);
  }
  return data;
}

function lastFmUrl(
  key: string,
  method: string,
  username: string,
  period?: string,
  limit = 200,
  page = 1,
): URL {
  const url = new URL(LASTFM_URL);
  url.searchParams.set("method", method);
  url.searchParams.set("user", username);
  url.searchParams.set("api_key", key);
  url.searchParams.set("format", "json");
  if (period) {
    url.searchParams.set("period", period);
    url.searchParams.set("limit", String(limit));
    url.searchParams.set("page", String(page));
  }
  return url;
}

async function profileTracks(
  url: URL,
  env: Env,
  encodedUsername: string,
): Promise<Response> {
  let username: string;
  try {
    username = decodeURIComponent(encodedUsername).trim();
  } catch {
    return failure("invalid_username", 422);
  }
  const period = url.searchParams.get("period") ?? "7day";
  const page = Number(url.searchParams.get("page") ?? "1");
  if (!username || username.length > 64 || !PERIODS.has(period)) {
    return failure("invalid_username_or_period", 422);
  }
  if (
    Number(url.searchParams.get("limit") ?? "50") !== 50 ||
    !Number.isInteger(page) ||
    page < 1 ||
    page > 4
  ) {
    return failure("invalid_page_or_limit", 422);
  }
  if (!env.LASTFM_API_KEY) return failure("lastfm_key_missing", 503);

  const started = performance.now();
  try {
    const upstream = await fetch(
      lastFmUrl(
        env.LASTFM_API_KEY,
        "user.gettoptracks",
        username,
        period,
        50,
        page,
      ),
      {
        headers: {
          Accept: "application/json",
          "User-Agent": `timbre-palette/${API_VERSION}`,
        },
      },
    );
    if (!upstream.ok) return failure("lastfm_unavailable", 502);
    console.log({
      event: "profile_tracks",
      period,
      page,
      limit: 50,
      wall_ms: Math.round(performance.now() - started),
    });
    // Pass the upstream JSON stream through. The browser parses it; the
    // Last.fm API key is never copied into the response.
    return new Response(upstream.body, {
      status: 200,
      headers: JSON_HEADERS,
    });
  } catch (error) {
    console.error({
      event: "profile_tracks_failed",
      code: "lastfm_unavailable",
      error_type: error instanceof Error ? error.name : "UnknownError",
    });
    return failure("lastfm_unavailable", 502);
  }
}

async function profileEvidence(request: Request, env: Env): Promise<Response> {
  if (!env.DB) return failure("database_unavailable", 503);
  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (contentLength > 16_384) return failure("request_too_large", 413);

  let input: Row | null;
  try {
    const body = await request.text();
    if (body.length > 16_384) return failure("request_too_large", 413);
    input = record(JSON.parse(body));
  } catch {
    return failure("invalid_json", 400);
  }
  if (!input) return failure("invalid_body", 422);
  const trackMbids = parseMbids(input.track_mbids);
  const artistMbids = parseMbids(input.artist_mbids);
  if (!trackMbids || !artistMbids) {
    return failure("invalid_mbid_list", 422);
  }
  const requestedVersion =
    input.snapshot_version === undefined ? null : text(input.snapshot_version);
  if (
    input.snapshot_version !== undefined &&
    (!requestedVersion || requestedVersion.length > 128)
  ) {
    return failure("invalid_snapshot_version", 422);
  }

  const started = performance.now();
  try {
    const snapshot = requestedVersion
      ? await env.DB.prepare(
          `
          SELECT snapshot_version, index_schema_version, manifest_hash,
                 object_prefix, methodology_version
          FROM musicbrainz_credit_index_snapshots
          WHERE snapshot_version = ?
          LIMIT 1
        `,
        )
          .bind(requestedVersion)
          .first<Row>()
      : await env.DB.prepare(
          `
          SELECT snapshot_version, index_schema_version, manifest_hash,
                 object_prefix, methodology_version
          FROM musicbrainz_credit_index_snapshots
          WHERE status = 'active'
          ORDER BY published_at DESC, created_at DESC
          LIMIT 1
        `,
        ).first<Row>();
    if (!snapshot) throw new ApiError("snapshot_unavailable", 503);
    if (snapshot.index_schema_version !== SNAPSHOT_SCHEMA_VERSION) {
      throw new ApiError("unsupported_snapshot_schema", 503);
    }
    const version = String(snapshot.snapshot_version);
    const trackIds = JSON.stringify(trackMbids);
    const artistIds = JSON.stringify(artistMbids);
    const [aliases, artistStatuses, vocabulary] = await Promise.all([
      trackMbids.length
        ? all(
            env.DB.prepare(
              `
        SELECT track_mbid, recording_mbid
        FROM snapshot_track_aliases
        WHERE snapshot_version = ?
          AND track_mbid IN (SELECT value FROM json_each(?))
      `,
            ).bind(version, trackIds),
          )
        : Promise.resolve([]),
      artistMbids.length
        ? all(
            env.DB.prepare(
              `
        SELECT artist_mbid, status
        FROM snapshot_artists
        WHERE snapshot_version = ?
          AND artist_mbid IN (SELECT value FROM json_each(?))
      `,
            ).bind(version, artistIds),
          )
        : Promise.resolve([]),
      artistMbids.length
        ? all(
            env.DB.prepare(
              `
        SELECT projection.artist_mbid, projection.instrument_slug,
               projection.family_slug, instruments.name AS instrument_name,
               families.name AS family_name, projection.distinct_recordings,
               projection.documented_recordings, projection.prevalence,
               projection.evidence_quality, projection.source_scope
        FROM snapshot_artist_instruments AS projection
        JOIN instruments ON instruments.slug = projection.instrument_slug
        JOIN instrument_families AS families ON families.slug = projection.family_slug
        WHERE projection.snapshot_version = ?
          AND projection.artist_mbid IN (SELECT value FROM json_each(?))
        ORDER BY projection.artist_mbid, projection.instrument_slug
      `,
            ).bind(version, artistIds),
          )
        : Promise.resolve([]),
    ]);
    const aliasesByTrack = new Map(
      aliases.map((row) => [
        String(row.track_mbid).toLowerCase(),
        String(row.recording_mbid).toLowerCase(),
      ]),
    );
    const recordingMbids = unique(
      trackMbids.map((mbid) => aliasesByTrack.get(mbid) ?? mbid),
    );
    const recordingIds = JSON.stringify(recordingMbids);
    const [recordingStatuses, recordingClaims] = await Promise.all([
      recordingMbids.length
        ? all(
            env.DB.prepare(
              `
        SELECT recording_mbid, status
        FROM snapshot_recordings
        WHERE snapshot_version = ?
          AND recording_mbid IN (SELECT value FROM json_each(?))
        UNION ALL
        SELECT target_mbid AS recording_mbid, 'failed' AS status
        FROM snapshot_hydration_jobs
        WHERE snapshot_version = ? AND target_kind = 'track'
          AND status = 'failed' AND attempts >= 5
          AND target_mbid IN (SELECT value FROM json_each(?))
      `,
            ).bind(version, recordingIds, version, recordingIds),
          )
        : Promise.resolve([]),
      recordingMbids.length
        ? all(
            env.DB.prepare(
              `
        SELECT projection.recording_mbid, projection.claim_level,
               projection.subject_slug, projection.instrument_slug,
               projection.family_slug, instruments.name AS instrument_name,
               families.name AS family_name,
               COALESCE(instruments.sound_nature, families.sound_nature) AS sound_nature
        FROM snapshot_recording_instruments AS projection
        LEFT JOIN instruments ON instruments.slug = projection.instrument_slug
        JOIN instrument_families AS families ON families.slug = projection.family_slug
        WHERE projection.snapshot_version = ?
          AND projection.recording_mbid IN (SELECT value FROM json_each(?))
          AND projection.scope IN ('recording', 'track')
        ORDER BY projection.recording_mbid, projection.instrument_slug
      `,
            ).bind(version, recordingIds),
          )
        : Promise.resolve([]),
    ]);
    const result = {
      snapshot,
      aliases,
      recording_statuses: recordingStatuses,
      recording_claims: recordingClaims,
      artist_statuses: artistStatuses,
      artist_vocabulary: vocabulary,
      counts: {
        tracks: trackMbids.length,
        artists: artistMbids.length,
        aliases: aliases.length,
        recording_statuses: recordingStatuses.length,
        recording_claims: recordingClaims.length,
        artist_statuses: artistStatuses.length,
        vocabulary_rows: vocabulary.length,
      },
      wall_ms: Math.round(performance.now() - started),
    };
    console.log({
      event: "profile_evidence",
      ...result.counts,
      wall_ms: result.wall_ms,
    });
    return json(result);
  } catch (error) {
    const code = error instanceof ApiError ? error.code : "api_unavailable";
    const status = error instanceof ApiError ? error.status : 503;
    console.error({ event: "profile_evidence_failed", code });
    return failure(code, status);
  }
}

async function scheduleHydration(
  request: Request,
  env: Env,
): Promise<Response> {
  if (!env.DB) return failure("database_unavailable", 503);
  const input = await readJsonBody(request, 16_384);
  if (input instanceof Response) return input;
  const snapshotVersion = text(input.snapshot_version);
  const rawRecordingTargets = input.recording_targets;
  const rawArtistMbids = input.artist_mbids;
  if (
    !snapshotVersion ||
    snapshotVersion.length > 128 ||
    !Array.isArray(rawRecordingTargets) ||
    rawRecordingTargets.length > 50 ||
    !Array.isArray(rawArtistMbids) ||
    rawArtistMbids.length > 200
  ) {
    return failure("invalid_hydration_request", 422);
  }

  const targets: { kind: "track" | "recording" | "artist"; mbid: string }[] =
    [];
  for (const value of rawRecordingTargets) {
    const row = record(value);
    const kind = row?.kind;
    const mbid = text(row?.mbid)?.toLowerCase();
    if (
      (kind !== "track" && kind !== "recording") ||
      !mbid ||
      !MBID_PATTERN.test(mbid)
    ) {
      return failure("invalid_hydration_target", 422);
    }
    targets.push({ kind, mbid });
  }
  const artistMbids: string[] = [];
  for (const value of rawArtistMbids) {
    const mbid = text(value)?.toLowerCase();
    if (!mbid || !MBID_PATTERN.test(mbid))
      return failure("invalid_artist_mbid", 422);
    artistMbids.push(mbid);
  }
  for (const mbid of [...new Set(artistMbids)])
    targets.push({ kind: "artist", mbid });

  const uniqueTargets = [
    ...new Map(
      targets.map((target) => [`${target.kind}:${target.mbid}`, target]),
    ).values(),
  ];
  const started = performance.now();
  try {
    const snapshot = await env.DB.prepare(
      `
      SELECT snapshot_version, index_schema_version
      FROM musicbrainz_credit_index_snapshots
      WHERE snapshot_version = ?
      LIMIT 1
    `,
    )
      .bind(snapshotVersion)
      .first<Row>();
    if (!snapshot) throw new ApiError("snapshot_unavailable", 503);
    if (snapshot.index_schema_version !== SNAPSHOT_SCHEMA_VERSION) {
      throw new ApiError("unsupported_snapshot_schema", 503);
    }
    if (uniqueTargets.length) {
      const payload = JSON.stringify(uniqueTargets);
      await env.DB.prepare(
        `
        INSERT OR IGNORE INTO snapshot_hydration_jobs
          (snapshot_version, target_kind, target_mbid, shard_key)
        SELECT ?, json_extract(value, '$.kind'), json_extract(value, '$.mbid'),
          substr(json_extract(value, '$.mbid'), 1,
            CASE WHEN json_extract(value, '$.kind') = 'artist' THEN 3 ELSE 4 END)
        FROM json_each(?)
      `,
      )
        .bind(snapshotVersion, payload)
        .run();
    }
    const wallMs = Math.round(performance.now() - started);
    console.log({
      event: "hydration_scheduled",
      target_count: uniqueTargets.length,
      wall_ms: wallMs,
    });
    return json(
      { accepted: uniqueTargets.length, snapshot_version: snapshotVersion },
      202,
    );
  } catch (error) {
    const code =
      error instanceof ApiError ? error.code : "hydration_unavailable";
    const status = error instanceof ApiError ? error.status : 503;
    console.error({ event: "hydration_schedule_failed", code });
    return failure(code, status);
  }
}

async function readJsonBody(
  request: Request,
  maxBytes: number,
): Promise<Row | Response> {
  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (contentLength > maxBytes) return failure("request_too_large", 413);
  try {
    const body = await request.text();
    if (body.length > maxBytes) return failure("request_too_large", 413);
    const value = record(JSON.parse(body));
    return value ?? failure("invalid_body", 422);
  } catch {
    return failure("invalid_json", 400);
  }
}

function parseMbids(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length > 50) return null;
  const normalized: string[] = [];
  for (const item of value) {
    if (typeof item !== "string" || !MBID_PATTERN.test(item)) return null;
    normalized.push(item.toLowerCase());
  }
  return [...new Set(normalized)].sort();
}

function parseTracks(value: unknown, limit: number): Track[] {
  const candidates = Array.isArray(value) ? value : value ? [value] : [];
  const tracks: Track[] = [];
  for (const candidate of candidates.slice(0, limit)) {
    const row = record(candidate);
    if (!row) continue;
    const artistData = record(row.artist);
    const title = text(row.name);
    const artist = text(artistData?.name) ?? text(row.artist);
    const playCount = Number(row.playcount);
    if (!title || !artist || !Number.isInteger(playCount) || playCount < 0)
      continue;
    tracks.push({
      title,
      artist,
      play_count: playCount,
      mbid: text(row.mbid),
      artist_mbid: text(artistData?.mbid),
      release_mbid: text(record(row.album)?.mbid),
      lastfm_url: text(row.url),
    });
  }
  return tracks;
}

function unique(values: (string | null)[]): string[] {
  return [
    ...new Set(
      values
        .filter((value): value is string => Boolean(value))
        .map((value) => value.toLowerCase()),
    ),
  ].sort();
}

async function all(statement: D1PreparedStatement): Promise<Row[]> {
  const result = await statement.all<Row>();
  return result.results ?? [];
}

function record(value: unknown): Row | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Row)
    : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function nonnegativeInteger(value: unknown): number | null {
  const number = Number(value);
  return value !== null &&
    value !== undefined &&
    Number.isInteger(number) &&
    number >= 0
    ? number
    : null;
}

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: JSON_HEADERS,
  });
}

function failure(code: string, status: number): Response {
  return json(
    {
      error: code,
      message: ERROR_MESSAGES[code] ?? "The request could not be completed.",
    },
    status,
  );
}
