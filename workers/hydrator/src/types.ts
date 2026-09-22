export const SERVING_SCHEMA_VERSION = "musicbrainz-instrument-credits-serving-v2";
export const MAX_ATTEMPTS = 5;
export const PROCESSING_LEASE_MINUTES = 10;

export type TargetKind = "track" | "recording" | "artist";
export type ClaimLevel = "instrument" | "family";
export type ClaimScope = "recording" | "track" | "release";

export interface SnapshotRow {
  snapshot_version: string;
  index_schema_version: string;
  manifest_hash: string;
  object_prefix: string;
  methodology_version: string | null;
}

export interface JobRow extends SnapshotRow {
  id: number;
  target_kind: TargetKind;
  target_mbid: string;
  shard_key: string;
  status: "pending" | "processing" | "failed";
  attempts: number;
}

export interface ServingClaim {
  instrument_mbid?: string;
  instrument_name: string;
  attributes?: string[];
  scope: ClaimScope;
  source_url?: string;
  source_urls?: string[];
  relation_type: string;
  production_method: string;
  credit_count: number;
  performer_count: number;
}

export interface ServingRecord {
  recording_mbid: string;
  source_url: string;
  claims: ServingClaim[];
}

export interface RecordingShard {
  schema_version: string;
  snapshot_version: string;
  shard: string;
  records: Record<string, ServingRecord>;
}

export interface AliasShard {
  schema_version: string;
  snapshot_version: string;
  shard: string;
  aliases: Record<string, string>;
}

export interface VocabularyEntry {
  instrument_mbid: string;
  instrument_name: string;
  distinct_recordings: number;
  documented_recordings: number;
  prevalence: number;
  qualifying: boolean;
}

export interface ServingArtist {
  artist_mbid: string;
  artist_name?: string;
  entries: VocabularyEntry[];
}

export interface VocabularyShard {
  schema_version: string;
  snapshot_version: string;
  shard: string;
  artists: Record<string, ServingArtist>;
}

export interface MappedRecordingClaim {
  claim_level: ClaimLevel;
  subject_slug: string;
  instrument_slug: string | null;
  family_slug: string;
  scope: ClaimScope;
  credit_count: number;
  performer_count: number;
  source_url: string | null;
}

export interface MappedArtistEntry {
  instrument_slug: string;
  family_slug: string;
  distinct_recordings: number;
  documented_recordings: number;
  prevalence: number;
  qualifying: boolean;
}
