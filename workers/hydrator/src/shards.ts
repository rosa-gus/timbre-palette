import {
  SERVING_SCHEMA_VERSION,
  type AliasShard,
  type RecordingShard,
  type SnapshotRow,
  type TargetKind,
  type VocabularyShard,
} from "./types";

const MAX_COMPRESSED_BYTES = 256 * 1024;
const MAX_DECOMPRESSED_BYTES = 1024 * 1024;

export class ShardError extends Error {
  constructor(
    message: string,
    readonly terminal: boolean,
  ) {
    super(message);
    this.name = "ShardError";
  }
}

export type Shard = RecordingShard | AliasShard | VocabularyShard;

export function shardKey(kind: TargetKind, mbid: string): string {
  return mbid.trim().toLowerCase().slice(0, kind === "artist" ? 3 : 4);
}

export function shardObjectKey(
  snapshot: SnapshotRow,
  kind: TargetKind,
  shard: string,
): string {
  const prefix = snapshot.object_prefix.replace(/\/+$/, "");
  const directory = kind === "track" ? "tracks" : `${kind}s`;
  return `${prefix}/${directory}/${shard}.json.gz`;
}

export async function readShard(
  bucket: R2Bucket,
  snapshot: SnapshotRow,
  kind: TargetKind,
  shard: string,
): Promise<Shard> {
  const key = shardObjectKey(snapshot, kind, shard);
  const object = await bucket.get(key);
  if (object === null) {
    throw new ShardError(`R2 object not found: ${key}`, true);
  }
  if (!("body" in object) || object.body === undefined) {
    throw new ShardError(`R2 object has no body: ${key}`, true);
  }
  if (object.size > MAX_COMPRESSED_BYTES) {
    throw new ShardError(
      `R2 object exceeds compressed size limit: ${key} (${object.size} bytes)`,
      true,
    );
  }

  let decodedBytes = 0;
  const bounded = new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      decodedBytes += chunk.byteLength;
      if (decodedBytes > MAX_DECOMPRESSED_BYTES) {
        controller.error(
          new ShardError(`decompressed shard exceeds size limit: ${key}`, true),
        );
        return;
      }
      controller.enqueue(chunk);
    },
  });

  try {
    const decompressed = object.body
      .pipeThrough(new DecompressionStream("gzip"))
      .pipeThrough(bounded);
    const value: unknown = await new Response(decompressed).json();
    return validateShard(value, snapshot, kind, shard, key);
  } catch (error) {
    if (error instanceof ShardError) {
      throw error;
    }
    throw new ShardError(
      `invalid gzip or JSON in ${key}: ${errorMessage(error)}`,
      true,
    );
  }
}

function validateShard(
  value: unknown,
  snapshot: SnapshotRow,
  kind: TargetKind,
  shard: string,
  key: string,
): Shard {
  if (!isRecord(value)) {
    throw new ShardError(`shard root is not an object: ${key}`, true);
  }
  if (value.schema_version !== SERVING_SCHEMA_VERSION) {
    throw new ShardError(`unsupported schema in ${key}`, true);
  }
  if (value.snapshot_version !== snapshot.snapshot_version) {
    throw new ShardError(`snapshot mismatch in ${key}`, true);
  }
  if (value.shard !== shard) {
    throw new ShardError(`shard name mismatch in ${key}`, true);
  }

  if (kind === "recording") {
    if (!isRecord(value.records)) {
      throw new ShardError(`recording shard has no records map: ${key}`, true);
    }
    for (const [mbid, record] of Object.entries(value.records)) {
      if (!mbid.startsWith(shard) || !isServingRecord(record)) {
        throw new ShardError(`invalid recording row in ${key}`, true);
      }
    }
    return value as unknown as RecordingShard;
  }

  if (kind === "track") {
    if (!isRecord(value.aliases)) {
      throw new ShardError(`track shard has no aliases map: ${key}`, true);
    }
    for (const [mbid, recordingMbid] of Object.entries(value.aliases)) {
      if (!mbid.startsWith(shard) || typeof recordingMbid !== "string") {
        throw new ShardError(`invalid track alias in ${key}`, true);
      }
    }
    return value as unknown as AliasShard;
  }

  if (!isRecord(value.artists)) {
    throw new ShardError(`artist shard has no artists map: ${key}`, true);
  }
  for (const [mbid, artist] of Object.entries(value.artists)) {
    if (!mbid.startsWith(shard) || !isServingArtist(artist)) {
      throw new ShardError(`invalid artist row in ${key}`, true);
    }
  }
  return value as unknown as VocabularyShard;
}

function isServingRecord(value: unknown): boolean {
  if (!isRecord(value) || typeof value.recording_mbid !== "string") {
    return false;
  }
  if (!Array.isArray(value.claims) || "credits" in value) {
    return false;
  }
  return value.claims.every(isServingClaim);
}

function isServingClaim(value: unknown): boolean {
  if (!isRecord(value)) {
    return false;
  }
  if (
    typeof value.instrument_name !== "string" ||
    !isScope(value.scope) ||
    typeof value.relation_type !== "string" ||
    typeof value.production_method !== "string" ||
    !isPositiveInteger(value.credit_count) ||
    !isNonNegativeInteger(value.performer_count)
  ) {
    return false;
  }
  if (value.instrument_mbid !== undefined && typeof value.instrument_mbid !== "string") {
    return false;
  }
  if (value.attributes !== undefined && !isStringArray(value.attributes)) {
    return false;
  }
  if (value.source_url !== undefined && typeof value.source_url !== "string") {
    return false;
  }
  return value.source_urls === undefined || isStringArray(value.source_urls);
}

function isServingArtist(value: unknown): boolean {
  if (!isRecord(value) || typeof value.artist_mbid !== "string") {
    return false;
  }
  return Array.isArray(value.entries) && value.entries.every(isVocabularyEntry);
}

function isVocabularyEntry(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.instrument_mbid === "string" &&
    typeof value.instrument_name === "string" &&
    isNonNegativeInteger(value.distinct_recordings) &&
    isNonNegativeInteger(value.documented_recordings) &&
    typeof value.prevalence === "number" &&
    Number.isFinite(value.prevalence) &&
    value.prevalence >= 0 &&
    value.prevalence <= 1 &&
    typeof value.qualifying === "boolean"
  );
}

function isScope(value: unknown): value is "recording" | "track" | "release" {
  return value === "recording" || value === "track" || value === "release";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isPositiveInteger(value: unknown): value is number {
  return isNonNegativeInteger(value) && value > 0;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
