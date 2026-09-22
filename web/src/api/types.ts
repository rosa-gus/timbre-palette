export type ListeningPeriod =
  | "overall"
  | "7day"
  | "1month"
  | "3month"
  | "6month"
  | "12month";

export type AnalysisStatus = "partial" | "ready" | "insufficient";
export type Confidence = "documented" | "strongly_associated" | "estimated";
export type RecordingStatus =
  | "resolved"
  | "unresolved_identity"
  | "pending_enrichment"
  | "ambiguous"
  | "resolved_without_evidence"
  | "transient_failure"
  | "terminal_failure";

export type SectionAvailability =
  | "available"
  | "insufficient_coverage"
  | "insufficient_diversity"
  | "insufficient_nature_evidence"
  | "no_candidate";

export interface ProfileSummary {
  username: string;
  period: ListeningPeriod;
  tracks_analyzed: number;
  total_plays: number;
  profile_url?: string | null;
  avatar_url?: string | null;
  realname?: string | null;
  registered?: string | null;
}

export interface RecordingStatusCounts {
  resolved: number;
  unresolved_identity: number;
  pending_enrichment: number;
  ambiguous: number;
  resolved_without_evidence: number;
  transient_failure: number;
  terminal_failure: number;
}

export interface SectionAvailabilitySummary {
  families: SectionAvailability;
  sound_balance: SectionAvailability;
  discovery: SectionAvailability;
  temperament: SectionAvailability;
}

export interface VocalPresence {
  documented_tracks: number;
  documented_artists: number;
  documented_plays: number;
  track_ratio: number;
  play_ratio: number;
}

export interface AnalysisSummary {
  status: AnalysisStatus;
  data_source: "mock" | "hybrid" | "catalog";
  history_source: string;
  instrumentation_source: string;
  methodology_version: string;
  catalog_version: string | null;
  coverage_tracks: number;
  coverage_plays: number;
  recording_status_counts: RecordingStatusCounts;
  notice: string;
  section_availability: SectionAvailabilitySummary;
  vocal_presence: VocalPresence;
  image_catalog_version: string;
}

export interface ImageVariant {
  name: string;
  url: string;
  width: number;
  height: number;
}

export interface ImageCredit {
  photographer: string | null;
  provider: string | null;
  photo_url: string | null;
  photographer_url: string | null;
  license: string | null;
  license_url: string | null;
}

export interface InstrumentImage {
  asset_id: string;
  resolution: "exact" | "related" | "family";
  depicted_instrument_slug: string;
  alt: string;
  caption: string;
  variants: ImageVariant[];
  tone: { shadow: string; highlight: string };
  credit: ImageCredit;
}

export interface FamilyPresence {
  slug: string;
  name: string;
  share: number;
  evidence_count: number;
  confidence: Confidence;
  image: InstrumentImage | null;
  tone: { shadow: string; highlight: string } | null;
}

export interface SoundBalance {
  acoustic: number;
  electric: number;
  electronic: number;
  sampled: number;
  hybrid: number;
  unknown: number;
}

export interface Discovery {
  instrument_slug: string;
  title: string;
  summary: string;
  image: InstrumentImage | null;
}

export interface Temperament {
  title: string;
  summary: string;
  disclaimer: string;
}

export interface RecordingAnalysis {
  title: string;
  artist: string;
  play_count: number;
  mbid: string | null;
  lastfm_url: string | null;
  status: RecordingStatus;
  status_detail: string | null;
}

export interface PaletteReport {
  profile: ProfileSummary;
  analysis: AnalysisSummary;
  recordings: RecordingAnalysis[];
  families: FamilyPresence[];
  sound_balance: SoundBalance | null;
  discovery: Discovery | null;
  temperament: Temperament | null;
}

export type AnalysisV2Status = "available" | "pending" | "insufficient";
export type AnalysisView = "track_palette" | "artist_vocabulary";

export interface SnapshotInfo {
  snapshot_version: string;
  schema_version: string;
  manifest_hash: string;
  object_prefix: string;
  methodology_version: string;
}

export interface HydrationSummary {
  status: "complete" | "pending";
  pending_recordings: number;
  pending_artists: number;
  pending_aliases: number;
}

export interface ArtistVocabulary {
  status: AnalysisV2Status;
  methodology_version: string;
  availability: {
    status: AnalysisV2Status;
    reason: string;
    pending_artists: number;
    pending_tracks: number;
  };
  reach: {
    track_reach: number;
    play_reach: number;
    qualified_artists: number;
    total_artists: number;
    qualified_tracks: number;
    total_tracks: number;
    qualified_plays: number;
    total_plays: number;
    unresolved_artists: number;
    unresolved_tracks: number;
  };
  concentration: number;
  families: VocabularyFamily[];
  featured_artists: VocabularyFeaturedArtist[];
  notice: string;
}

export interface VocabularyFeaturedArtist {
  mbid: string;
  name: string;
  families: {
    slug: string;
    name: string;
    instruments: string[];
    tone: { shadow: string; highlight: string } | null;
  }[];
}

export interface VocabularyInstrument {
  slug: string;
  name: string;
  distinct_recordings: number;
  documented_recordings: number;
  prevalence: number;
  evidence: {
    source: "musicbrainz_snapshot";
    scope: "recording" | "track";
    snapshot_version: string;
    quality: number;
    documented_recordings: number;
  };
}

export interface VocabularyFamily {
  slug: string;
  name: string;
  score: number;
  share: number;
  prevalence: number;
  supporting_artists: number;
  instruments: VocabularyInstrument[];
  tone: { shadow: string; highlight: string } | null;
}

export interface ProfileAnalysisV2 {
  profile: ProfileSummary;
  snapshot: SnapshotInfo;
  track_palette: PaletteReport;
  artist_vocabulary: ArtistVocabulary;
  available_views: AnalysisView[];
  default_view: AnalysisView | null;
  hydration: HydrationSummary;
}

export interface EditorialReview {
  source_metadata_verified: boolean;
  claim_support_verified: boolean;
  reviewed_at: string | null;
  reviewer: string | null;
  editorial_note: string | null;
}

export interface EditorialCitation {
  source_id: string;
  locator: string | null;
  note: string | null;
}

export interface EditorialSection {
  id: string;
  kind: "curiosity";
  text: string;
  content_type: "fact" | "editorial_summary";
  status: "draft" | "sourced" | "reviewed" | "published" | "deprecated";
  review: EditorialReview;
  citations: EditorialCitation[];
}

export interface EditorialSource {
  id: string;
  title: string;
  contributors: string[];
  publisher: string | null;
  publication_date: string | null;
  url: string | null;
  accessed_at: string | null;
  verified_at: string | null;
  locator: string | null;
  source_type: string;
  language: string;
  license: string | null;
  note: string | null;
  metadata_verified: boolean;
}

export interface FurtherReading {
  title: string;
  url: string;
  publisher: string | null;
}

export interface InstrumentResource {
  data_source: "mock" | "catalog";
  catalog_version: string;
  image_catalog_version: string;
  slug: string;
  name: string;
  kind: "instrument" | "family";
  family_slug: string | null;
  description: string;
  sound_production: string;
  common_roles: string[];
  related_slugs: string[];
  sections: EditorialSection[];
  sources: EditorialSource[];
  further_reading: FurtherReading[];
  image: InstrumentImage | null;
  tone: { shadow: string; highlight: string } | null;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
}
