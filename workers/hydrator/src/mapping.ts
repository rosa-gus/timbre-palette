import type {
  ServingClaim,
  ServingArtist,
  MappedArtistEntry,
  MappedRecordingClaim,
} from "./types";

interface ExternalMappingRow {
  external_id: string;
  instrument_slug: string;
  family_slug: string;
}

interface AliasMappingRow {
  claim_level: "instrument" | "family";
  normalized_alias: string;
  instrument_slug: string | null;
  family_slug: string;
}

interface InstrumentMapping {
  instrumentSlug: string;
  familySlug: string;
}

interface FamilyMapping {
  familySlug: string;
}

interface TaxonomyMappings {
  byExternalId: Map<string, InstrumentMapping>;
  byName: Map<string, InstrumentMapping | FamilyMapping>;
}

export interface RecordingMappingResult {
  claims: MappedRecordingClaim[];
  creditCount: number;
  mappedCreditCount: number;
  discardedCreditCount: number;
}

export interface ArtistMappingResult {
  entries: MappedArtistEntry[];
  entryCount: number;
  mappedEntryCount: number;
  discardedEntryCount: number;
}

export async function mapRecordingClaims(
  db: D1Database,
  claims: ServingClaim[],
): Promise<RecordingMappingResult> {
  const mappings = await loadMappings(
    db,
    claims.map((claim) => claim.instrument_name),
    claims.map((claim) => claim.instrument_mbid),
  );
  const grouped = new Map<string, MappedRecordingClaim>();
  let creditCount = 0;
  let mappedCreditCount = 0;

  for (const claim of claims) {
    creditCount += claim.credit_count;
    const mapping = resolveClaim(mappings, claim);
    if (mapping === null) {
      continue;
    }
    mappedCreditCount += claim.credit_count;
    const key = `${mapping.claimLevel}|${mapping.subjectSlug}|${claim.scope}`;
    const current = grouped.get(key);
    const sourceUrl = firstSourceUrl(claim);
    if (current === undefined) {
      grouped.set(key, {
        claim_level: mapping.claimLevel,
        subject_slug: mapping.subjectSlug,
        instrument_slug: mapping.instrumentSlug,
        family_slug: mapping.familySlug,
        scope: claim.scope,
        credit_count: claim.credit_count,
        performer_count: claim.performer_count,
        source_url: sourceUrl,
      });
    } else {
      current.credit_count += claim.credit_count;
      current.performer_count += claim.performer_count;
      current.source_url = chooseSourceUrl(current.source_url, sourceUrl);
    }
  }

  return {
    claims: [...grouped.values()].sort(compareMappedClaims),
    creditCount,
    mappedCreditCount,
    discardedCreditCount: creditCount - mappedCreditCount,
  };
}

export async function mapArtistEntries(
  db: D1Database,
  artist: ServingArtist,
): Promise<ArtistMappingResult> {
  const mappings = await loadMappings(
    db,
    artist.entries.map((entry) => entry.instrument_name),
    artist.entries.map((entry) => entry.instrument_mbid),
  );
  const grouped = new Map<string, MappedArtistEntry>();
  let mappedEntryCount = 0;

  for (const entry of artist.entries) {
    const mapping = resolveInstrument(mappings, entry.instrument_mbid, entry.instrument_name);
    if (mapping === null) {
      continue;
    }
    mappedEntryCount += 1;
    const current = grouped.get(mapping.instrumentSlug);
    if (current === undefined) {
      grouped.set(mapping.instrumentSlug, {
        instrument_slug: mapping.instrumentSlug,
        family_slug: mapping.familySlug,
        distinct_recordings: entry.distinct_recordings,
        documented_recordings: entry.documented_recordings,
        prevalence: entry.prevalence,
        qualifying: entry.qualifying,
      });
    } else {
      current.distinct_recordings += entry.distinct_recordings;
      current.documented_recordings += entry.documented_recordings;
      current.prevalence = Math.max(current.prevalence, entry.prevalence);
      current.qualifying ||= entry.qualifying;
    }
  }

  return {
    entries: [...grouped.values()].sort((left, right) =>
      left.instrument_slug.localeCompare(right.instrument_slug),
    ),
    entryCount: artist.entries.length,
    mappedEntryCount,
    discardedEntryCount: artist.entries.length - mappedEntryCount,
  };
}

export function normalizeAlias(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

async function loadMappings(
  db: D1Database,
  names: (string | undefined)[],
  externalIds: (string | undefined)[],
): Promise<TaxonomyMappings> {
  const normalizedNames = [...new Set(names.map((name) => normalizeAlias(name ?? "")).filter(Boolean))];
  const ids = [...new Set(externalIds.filter((id): id is string => Boolean(id && id.trim())))];
  if (normalizedNames.length === 0 && ids.length === 0) {
    return { byExternalId: new Map(), byName: new Map() };
  }

  const statements: D1PreparedStatement[] = [];
  if (ids.length > 0) {
    statements.push(
      db
        .prepare(
          `
          SELECT identifiers.external_id, identifiers.instrument_slug,
                 instruments.family_slug
          FROM instrument_external_identifiers AS identifiers
          JOIN instruments ON instruments.slug = identifiers.instrument_slug
          WHERE identifiers.source = 'musicbrainz'
            AND identifiers.external_id IN (SELECT value FROM json_each(?))
          `,
        )
        .bind(JSON.stringify(ids)),
    );
  }
  if (normalizedNames.length > 0) {
    statements.push(
      db
        .prepare(
          `
          SELECT 'instrument' AS claim_level, aliases.normalized_alias,
                 aliases.instrument_slug, instruments.family_slug
          FROM instrument_aliases AS aliases
          JOIN instruments ON instruments.slug = aliases.instrument_slug
          WHERE aliases.source = 'musicbrainz'
            AND aliases.locale = 'en'
            AND aliases.normalized_alias IN (SELECT value FROM json_each(?))
          UNION ALL
          SELECT 'family' AS claim_level, aliases.normalized_alias,
                 NULL AS instrument_slug, aliases.family_slug
          FROM instrument_family_aliases AS aliases
          WHERE aliases.source = 'musicbrainz'
            AND aliases.locale = 'en'
            AND aliases.normalized_alias IN (SELECT value FROM json_each(?))
          `,
        )
        .bind(JSON.stringify(normalizedNames), JSON.stringify(normalizedNames)),
    );
  }

  const results = await db.batch(statements);
  const byExternalId = new Map<string, InstrumentMapping>();
  const byName = new Map<string, InstrumentMapping | FamilyMapping>();
  let resultIndex = 0;

  if (ids.length > 0) {
    for (const row of rows<ExternalMappingRow>(results[resultIndex++])) {
      byExternalId.set(row.external_id, {
        instrumentSlug: row.instrument_slug,
        familySlug: row.family_slug,
      });
    }
  }
  if (normalizedNames.length > 0) {
    for (const row of rows<AliasMappingRow>(results[resultIndex] ?? {})) {
      const normalized = row.normalized_alias;
      if (row.claim_level === "instrument" && row.instrument_slug) {
        byName.set(normalized, {
          instrumentSlug: row.instrument_slug,
          familySlug: row.family_slug,
        });
      } else if (!byName.has(normalized)) {
        byName.set(normalized, { familySlug: row.family_slug });
      }
    }
  }
  return { byExternalId, byName };
}

function resolveClaim(
  mappings: TaxonomyMappings,
  claim: ServingClaim,
): {
  claimLevel: "instrument" | "family";
  subjectSlug: string;
  instrumentSlug: string | null;
  familySlug: string;
} | null {
  const external = claim.instrument_mbid
    ? mappings.byExternalId.get(claim.instrument_mbid)
    : undefined;
  if (external) {
    return {
      claimLevel: "instrument",
      subjectSlug: external.instrumentSlug,
      instrumentSlug: external.instrumentSlug,
      familySlug: external.familySlug,
    };
  }
  const byName = mappings.byName.get(normalizeAlias(claim.instrument_name));
  if (!byName) {
    return null;
  }
  if ("instrumentSlug" in byName) {
    return {
      claimLevel: "instrument",
      subjectSlug: byName.instrumentSlug,
      instrumentSlug: byName.instrumentSlug,
      familySlug: byName.familySlug,
    };
  }
  return {
    claimLevel: "family",
    subjectSlug: byName.familySlug,
    instrumentSlug: null,
    familySlug: byName.familySlug,
  };
}

function resolveInstrument(
  mappings: TaxonomyMappings,
  externalId: string,
  instrumentName: string,
): InstrumentMapping | null {
  const external = mappings.byExternalId.get(externalId);
  if (external) {
    return external;
  }
  const byName = mappings.byName.get(normalizeAlias(instrumentName));
  return byName && "instrumentSlug" in byName ? byName : null;
}

function firstSourceUrl(claim: ServingClaim): string | null {
  const sources = [
    ...(claim.source_urls ?? []),
    ...(claim.source_url ? [claim.source_url] : []),
  ].filter(Boolean);
  return sources.length === 0 ? null : [...new Set(sources)].sort()[0] ?? null;
}

function chooseSourceUrl(current: string | null, next: string | null): string | null {
  if (current === null) return next;
  if (next === null) return current;
  return current.localeCompare(next) <= 0 ? current : next;
}

function compareMappedClaims(left: MappedRecordingClaim, right: MappedRecordingClaim): number {
  return [left.claim_level, left.subject_slug, left.scope].join("\u0000").localeCompare(
    [right.claim_level, right.subject_slug, right.scope].join("\u0000"),
  );
}

function rows<T>(result: D1Result | undefined): T[] {
  return (result?.results ?? []) as T[];
}
