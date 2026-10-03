import imageManifest from "../../../public/profile-analysis-catalog.json";
import { API_VERSION } from "./version";
import { ProtectionError } from "../../shared/protection";

type Row = Record<string, unknown>;
type Env = Cloudflare.Env;

const CORS_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Accept, Content-Type",
};

export async function catalogStats(env: Env): Promise<Response> {
  try {
    const row = await env.DB.prepare(
      `
      SELECT COUNT(DISTINCT recording_mbid) AS recordings_with_evidence
      FROM snapshot_recordings
      WHERE status = 'complete' AND mapped_credit_count > 0
        AND snapshot_version = (
          SELECT snapshot_version
          FROM musicbrainz_credit_index_snapshots
          WHERE status = 'active'
          ORDER BY published_at DESC, created_at DESC
          LIMIT 1
        )
    `,
    ).first<Row>();
    return json(
      { recordings_with_evidence: number(row?.recordings_with_evidence) },
      200,
      {
        "Cache-Control": "public, max-age=300, s-maxage=300",
      },
    );
  } catch (error) {
    if (error instanceof ProtectionError) throw error;
    console.error({
      event: "catalog_stats_failed",
      error_type: errorType(error),
    });
    return failure(
      "catalog_unavailable",
      "Catalog statistics are unavailable.",
      503,
    );
  }
}

export async function getInstrument(
  url: URL,
  env: Env,
  encodedSlug: string,
): Promise<Response> {
  let slug: string;
  try {
    slug = decodeURIComponent(encodedSlug).trim().toLowerCase();
  } catch {
    return failure("invalid_slug", "The instrument slug is invalid.", 422);
  }
  if (!slug || slug.length > 80) {
    return failure("invalid_slug", "The instrument slug is invalid.", 422);
  }

  try {
    const alias = await env.DB.prepare(
      `
      SELECT canonical_slug FROM instrument_slug_aliases WHERE alias_slug = ?
      UNION ALL
      SELECT canonical_slug FROM family_slug_aliases WHERE alias_slug = ?
      LIMIT 1
    `,
    )
      .bind(slug, slug)
      .first<Row>();
    const canonicalSlug = string(alias?.canonical_slug) ?? slug;
    let row = await env.DB.prepare(
      `
      SELECT slug, name, family_slug, description, sound_production
      FROM instruments WHERE slug = ?
    `,
    )
      .bind(canonicalSlug)
      .first<Row>();
    let kind: "instrument" | "family" = "instrument";
    let familySlug: string | null = null;
    if (row) {
      familySlug = string(row.family_slug);
    } else {
      row = await env.DB.prepare(
        `
        SELECT slug, name, description, sound_production
        FROM instrument_families WHERE slug = ?
      `,
      )
        .bind(canonicalSlug)
        .first<Row>();
      kind = "family";
      if (!row)
        return failure(
          "instrument_not_found",
          "Instrument or sound family not found.",
          404,
        );
    }

    const [
      catalogVersionRow,
      roleRows,
      relatedRows,
      editorialRows,
      readingRows,
    ] = await Promise.all([
      env.DB.prepare(
        `
        SELECT version FROM catalog_versions ORDER BY published_at DESC, id DESC LIMIT 1
      `,
      ).first<Row>(),
      all(
        env.DB.prepare(
          kind === "instrument"
            ? "SELECT role FROM instrument_common_roles WHERE instrument_slug = ? ORDER BY id"
            : "SELECT role FROM instrument_common_roles WHERE family_slug = ? ORDER BY id",
        ).bind(canonicalSlug),
      ),
      all(
        env.DB.prepare(
          `
        SELECT target_slug FROM instrument_relations WHERE source_slug = ? ORDER BY id
      `,
        ).bind(canonicalSlug),
      ),
      editorialContent(env, canonicalSlug, kind),
      all(
        env.DB.prepare(
          kind === "instrument"
            ? `SELECT title, url, publisher FROM instrument_further_reading
           WHERE instrument_slug = ? AND status IN ('reviewed', 'published') ORDER BY position, id`
            : `SELECT title, url, publisher FROM instrument_further_reading
           WHERE family_slug = ? AND status IN ('reviewed', 'published') ORDER BY position, id`,
        ).bind(canonicalSlug),
      ),
    ]);

    const version = string(catalogVersionRow?.version) ?? "unknown";
    const familyForImage = familySlug ?? canonicalSlug;
    const image = resolveImage(
      canonicalSlug,
      familyForImage,
      env.IMAGE_ASSET_BASE_URL ?? "",
    );
    const familyTone = tone(familyForImage);
    const resource = {
      data_source: "catalog",
      catalog_version: version,
      image_catalog_version: imageManifest.catalog_version,
      slug: string(row.slug) ?? canonicalSlug,
      name: string(row.name) ?? canonicalSlug,
      kind,
      family_slug: familySlug,
      description: string(row.description) ?? "",
      sound_production: string(row.sound_production) ?? "",
      common_roles: roleRows.map((item) => string(item.role)).filter(isString),
      related_slugs: relatedRows
        .map((item) => string(item.target_slug))
        .filter(isString),
      sections: editorialRows.sections,
      sources: editorialRows.sources,
      further_reading: readingRows.map((item) => ({
        title: string(item.title) ?? "",
        url: string(item.url) ?? "",
        publisher: string(item.publisher),
      })),
      image,
      tone: familyTone,
    };
    return json(resource, 200, {
      "Cache-Control": "public, max-age=300, s-maxage=300",
    });
  } catch (error) {
    if (error instanceof ProtectionError) throw error;
    console.error({
      event: "instrument_catalog_failed",
      slug,
      error_type: errorType(error),
    });
    return failure(
      "catalog_unavailable",
      "The instrument catalog is unavailable.",
      503,
    );
  }
}

async function editorialContent(
  env: Env,
  slug: string,
  kind: "instrument" | "family",
): Promise<{ sections: Row[]; sources: Row[] }> {
  const subjectColumn =
    kind === "instrument" ? "instrument_slug" : "family_slug";
  const rows = await all(
    env.DB.prepare(
      `
    SELECT b.id AS block_id, b.section_kind, b.text, b.content_type,
           b.status, b.claim_support_verified, b.reviewed_at,
           b.reviewer, b.editorial_note,
           c.source_id, c.locator, c.citation_note,
           s.title AS source_title, s.contributors_json,
           s.publisher, s.publication_date, s.url,
           s.accessed_at, s.source_locator, s.source_type,
           s.language, s.license, s.source_note,
           s.metadata_verified, s.verified_at
    FROM editorial_content_blocks AS b
    LEFT JOIN editorial_content_citations AS c ON c.block_id = b.id
    LEFT JOIN editorial_sources AS s ON s.id = c.source_id
    WHERE b.${subjectColumn} = ?
      AND b.section_kind = 'curiosity'
      AND length(trim(b.text)) > 0
      AND b.status IN ('sourced', 'reviewed', 'published')
      AND b.claim_support_verified = 1
      AND EXISTS (
        SELECT 1 FROM editorial_content_citations AS eligible
        WHERE eligible.block_id = b.id
      )
      AND NOT EXISTS (
        SELECT 1
        FROM editorial_content_citations AS ineligible
        LEFT JOIN editorial_sources AS source ON source.id = ineligible.source_id
        WHERE ineligible.block_id = b.id
          AND COALESCE(source.metadata_verified, 0) <> 1
      )
    ORDER BY b.id, c.source_id
  `,
    ).bind(slug),
  );

  const blocks = new Map<string, Row>();
  const sources = new Map<string, Row>();
  const sourceVerified = new Map<string, boolean>();
  for (const row of rows) {
    const blockId = string(row.block_id);
    if (!blockId) continue;
    let block = blocks.get(blockId);
    if (!block) {
      block = {
        id: blockId,
        kind: string(row.section_kind) ?? "curiosity",
        text: string(row.text) ?? "",
        content_type: string(row.content_type) ?? "editorial_summary",
        status: string(row.status) ?? "draft",
        claim_support_verified: Boolean(row.claim_support_verified),
        reviewed_at: string(row.reviewed_at),
        reviewer: string(row.reviewer),
        editorial_note: string(row.editorial_note),
        citations: [],
      };
      blocks.set(blockId, block);
    }
    const sourceId = string(row.source_id);
    if (!sourceId) continue;
    const citations = block.citations as Row[];
    citations.push({
      source_id: sourceId,
      locator: string(row.locator),
      note: string(row.citation_note),
    });
    const metadataVerified = Boolean(row.metadata_verified);
    sourceVerified.set(
      sourceId,
      (sourceVerified.get(sourceId) ?? true) && metadataVerified,
    );
    if (!sources.has(sourceId)) {
      let contributors: string[] = [];
      try {
        const parsed: unknown = JSON.parse(
          string(row.contributors_json) ?? "[]",
        );
        if (Array.isArray(parsed)) contributors = parsed.filter(isString);
      } catch {
        contributors = [];
      }
      sources.set(sourceId, {
        id: sourceId,
        title: string(row.source_title) ?? sourceId,
        contributors,
        publisher: string(row.publisher),
        publication_date: string(row.publication_date),
        url: string(row.url),
        accessed_at: string(row.accessed_at),
        verified_at: string(row.verified_at),
        locator: string(row.source_locator),
        source_type: string(row.source_type) ?? "unknown",
        language: string(row.language) ?? "en",
        license: string(row.license),
        note: string(row.source_note),
        metadata_verified: metadataVerified,
      });
    }
  }

  const sections = [...blocks.values()].map((block) => {
    const citations = block.citations as Row[];
    return {
      ...block,
      review: {
        source_metadata_verified:
          citations.length > 0 &&
          citations.every(
            (citation) =>
              sourceVerified.get(String(citation.source_id)) === true,
          ),
        claim_support_verified: block.claim_support_verified,
        reviewed_at: block.reviewed_at,
        reviewer: block.reviewer,
        editorial_note: block.editorial_note,
      },
    };
  });
  return { sections, sources: [...sources.values()] };
}

function resolveImage(
  slug: string,
  familySlug: string,
  baseUrl: string,
): Row | null {
  const imageItems = imageManifest.images as Row[];
  const imageById = new Map(
    imageItems.map((item) => [String(item.slug ?? ""), item]),
  );
  const candidates: {
    assetId: string;
    resolution: "exact" | "related" | "family";
  }[] = [];
  const instrumentImages = imageManifest.instrument_images as Record<
    string,
    string
  >;
  const fallbacks = imageManifest.instrument_fallbacks as Record<
    string,
    string
  >;
  const familyImages = imageManifest.family_images as Record<
    string,
    { asset_id?: string }
  >;
  if (instrumentImages[slug])
    candidates.push({ assetId: instrumentImages[slug], resolution: "exact" });
  if (fallbacks[slug])
    candidates.push({ assetId: fallbacks[slug], resolution: "related" });
  if (familyImages[familySlug]?.asset_id)
    candidates.push({
      assetId: familyImages[familySlug].asset_id!,
      resolution: "family",
    });
  const familyNames = imageManifest.family_names as Record<string, string>;
  const defaults = imageManifest.defaults as Record<string, unknown>;
  for (const candidate of candidates) {
    const image = imageById.get(candidate.assetId);
    const publication = object(image?.publication);
    if (
      !image ||
      !["approved", "published"].includes(String(publication.status ?? "draft"))
    )
      continue;
    const variants = Array.isArray(image.variants)
      ? image.variants.filter(isObject)
      : [];
    if (
      variants.some((variant) => String(variant.url ?? "").includes("<hash>"))
    )
      continue;
    const variant =
      variants.find((item) => item.name === "detail") ?? variants[0];
    const rawUrl =
      string(variant?.url) ?? string(publication.url) ?? string(image.output);
    if (!rawUrl) continue;
    const assetBase =
      (baseUrl || "https://rosa-gus.github.io/timbre-palette/").replace(
        /\/+$/,
        "",
      ) + "/";
    const relativeUrl = rawUrl
      .replace(/^https?:\/\/[^/]+\//, "")
      .replace(/^\/+/, "");
    let url: string;
    try {
      url = new URL(relativeUrl, assetBase).toString();
    } catch {
      continue;
    }
    const imageFamily = string(image.family_slug) ?? familySlug;
    const depicted =
      string(image.instrument_slug) ?? string(image.slug) ?? slug;
    const label = string(image.depicted_name) ?? depicted;
    const caption =
      candidate.resolution === "family"
        ? `Imagem ilustrativa da família ${familyNames[imageFamily] ?? imageFamily}: ${label}.`
        : candidate.resolution === "related"
          ? `Imagem relacionada ao instrumento ${label}.`
          : `Imagem do instrumento ${label}.`;
    const treatment = { ...defaults, ...object(image.treatment) };
    const credit = object(image.credit);
    return {
      asset_id: candidate.assetId,
      resolution: candidate.resolution,
      depicted_instrument_slug: depicted,
      alt: string(image.alt) ?? `Imagem de ${label}.`,
      caption,
      variants: [
        {
          name: "detail",
          url,
          width: number(variant?.width),
          height: number(variant?.height),
        },
      ],
      tone: {
        shadow: string(treatment.shadow) ?? "#000000",
        highlight: string(treatment.highlight) ?? "#f29191",
      },
      credit: {
        photographer: string(credit.photographer),
        provider: string(credit.provider),
        photo_url: string(credit.photo_url),
        photographer_url: string(credit.photographer_url),
        license: string(credit.license),
        license_url: string(credit.license_url),
      },
    };
  }
  return null;
}

function tone(familySlug: string): Row | null {
  const tones = imageManifest.family_tones as Record<string, Row>;
  const value = tones[familySlug];
  if (!value) return null;
  return {
    shadow: string(value.shadow) ?? "#000000",
    highlight: string(value.highlight) ?? "#f29191",
  };
}

export function openApiDocument(): Response {
  return json({
    openapi: "3.1.0",
    info: {
      title: "Timbre Palette API",
      version: API_VERSION,
      description:
        "Provides Last.fm profile data and snapshot evidence. The browser assembles profile analysis reports.",
    },
    servers: [{ url: "/" }],
    paths: {
      "/health": {
        get: {
          summary: "Check API health",
          responses: {
            "200": response("API health", {
              type: "object",
              properties: {
                status: { type: "string", const: "ok" },
                service: { type: "string", const: "timbre-palette-api" },
                version: { type: "string", example: API_VERSION },
              },
            }),
          },
        },
      },
      "/openapi.json": {
        get: {
          summary: "Get the OpenAPI document",
          responses: {
            "200": response("OpenAPI 3.1 document", { type: "object" }),
          },
        },
      },
      "/v3/profiles/{username}/tracks": {
        get: {
          summary: "Read one page of a public Last.fm listening history",
          description:
            "Returns validated Last.fm top-tracks JSON for one page. The API key remains server-side. Pages contain at most 50 tracks and page numbers are limited to 1–4. Provider errors are normalized; visitor and global admission limits apply.",
          parameters: [
            pathParameter("username", "Last.fm username"),
            queryParameter("period", "Listening period", {
              type: "string",
              enum: [
                "7day",
                "1month",
                "3month",
                "6month",
                "12month",
                "overall",
              ],
              default: "7day",
            }),
            queryParameter("page", "One-based page number", {
              type: "integer",
              minimum: 1,
              maximum: 4,
              default: 1,
            }),
            queryParameter("limit", "Page size; only 50 is accepted", {
              type: "integer",
              enum: [50],
              default: 50,
            }),
          ],
          responses: {
            "200": response("Last.fm top-tracks JSON", {
              type: "object",
              description: "Last.fm top-track history for the requested page.",
            }),
            ...errorResponses(["404", "422", "429", "502", "503"]),
          },
        },
      },
      "/v3/profiles/{username}/metadata": {
        get: {
          summary: "Read public Last.fm profile metadata",
          parameters: [pathParameter("username", "Last.fm username")],
          responses: {
            "200": response("Profile metadata", {
              type: "object",
              required: ["username", "profile"],
              properties: {
                username: { type: "string" },
                profile: {
                  type: "object",
                  description: "The Last.fm user.getinfo user object.",
                },
                wall_ms: {
                  type: "integer",
                  description: "Elapsed Worker time in milliseconds.",
                },
              },
            }),
            ...errorResponses(["404", "422", "429", "502", "503"]),
          },
        },
      },
      "/v3/evidence": {
        post: {
          summary: "Read snapshot evidence for a bounded batch of identities",
          description:
            "Reads aliases, recording statuses and claims, artist statuses, and artist vocabulary from one snapshot. Either MBID array may be empty. Supply snapshot_version after the first batch to keep subsequent reads pinned to the same snapshot.",
          requestBody: jsonRequestBody("Profile evidence request", {
            $ref: "#/components/schemas/ProfileEvidenceRequest",
          }),
          responses: {
            "200": response("Snapshot evidence batch", {
              type: "object",
              required: [
                "snapshot",
                "aliases",
                "recording_statuses",
                "recording_claims",
                "artist_statuses",
                "artist_vocabulary",
              ],
              properties: {
                snapshot: { $ref: "#/components/schemas/Snapshot" },
                aliases: { type: "array", items: { type: "object" } },
                recording_statuses: {
                  type: "array",
                  items: { type: "object" },
                },
                recording_claims: { type: "array", items: { type: "object" } },
                artist_statuses: { type: "array", items: { type: "object" } },
                artist_vocabulary: { type: "array", items: { type: "object" } },
                counts: { type: "object" },
                wall_ms: { type: "integer" },
              },
            }),
            ...errorResponses(["400", "413", "422", "429", "503"]),
          },
        },
      },
      "/v3/hydration": {
        post: {
          summary: "Queue bounded snapshot hydration targets",
          description:
            "Deduplicates and stores missing recording, track, and artist targets for the background snapshot hydrator. It does not wait for hydration to finish.",
          requestBody: jsonRequestBody("Hydration request", {
            $ref: "#/components/schemas/HydrationRequest",
          }),
          responses: {
            "202": response("Targets accepted for asynchronous processing", {
              $ref: "#/components/schemas/HydrationAccepted",
            }),
            ...errorResponses(["400", "413", "422", "429", "503"]),
          },
        },
      },
      "/v2/instruments/{slug}": {
        get: {
          summary: "Read a reviewed instrument or sound-family resource",
          parameters: [
            pathParameter("slug", "Instrument or sound-family slug"),
          ],
          responses: {
            "200": response("Editorial resource", { type: "object" }),
            ...errorResponses(["404", "422", "429", "503"]),
          },
        },
      },
      "/v2/catalog/stats": {
        get: {
          summary: "Read statistics for the active evidence catalog",
          responses: {
            "200": response("Catalog statistics", {
              type: "object",
              required: ["recordings_with_evidence"],
              properties: {
                recordings_with_evidence: { type: "integer", minimum: 0 },
              },
            }),
            ...errorResponses(["429", "503"]),
          },
        },
      },
    },
    components: {
      schemas: {
        ApiError: {
          type: "object",
          required: ["error", "message"],
          properties: {
            error: {
              type: "string",
              description: "Stable machine-readable error code.",
            },
            message: {
              type: "string",
              description: "English description of the error.",
            },
          },
        },
        ProfileEvidenceRequest: {
          type: "object",
          required: ["track_mbids", "artist_mbids"],
          properties: {
            track_mbids: {
              type: "array",
              maxItems: 50,
              items: { type: "string", format: "uuid" },
            },
            artist_mbids: {
              type: "array",
              maxItems: 50,
              items: { type: "string", format: "uuid" },
            },
            snapshot_version: {
              type: "string",
              maxLength: 128,
              description: "Optional snapshot pin for subsequent batches.",
            },
          },
        },
        HydrationRequest: {
          type: "object",
          required: ["snapshot_version", "recording_targets", "artist_mbids"],
          properties: {
            snapshot_version: { type: "string", maxLength: 128 },
            recording_targets: {
              type: "array",
              maxItems: 50,
              items: { $ref: "#/components/schemas/RecordingHydrationTarget" },
            },
            artist_mbids: {
              type: "array",
              maxItems: 200,
              items: { type: "string", format: "uuid" },
            },
          },
        },
        RecordingHydrationTarget: {
          type: "object",
          required: ["kind", "mbid"],
          properties: {
            kind: { type: "string", enum: ["track", "recording"] },
            mbid: { type: "string", format: "uuid" },
          },
        },
        Snapshot: {
          type: "object",
          required: [
            "snapshot_version",
            "index_schema_version",
            "manifest_hash",
            "object_prefix",
            "methodology_version",
          ],
          properties: {
            snapshot_version: { type: "string" },
            index_schema_version: { type: "string" },
            manifest_hash: { type: "string" },
            object_prefix: { type: "string" },
            methodology_version: { type: "string" },
          },
        },
        HydrationAccepted: {
          type: "object",
          required: ["accepted", "snapshot_version"],
          properties: {
            accepted: { type: "integer", minimum: 0 },
            inserted: { type: "integer", minimum: 0, description: "New jobs inserted; repeated targets do not consume new-job budget." },
            snapshot_version: { type: "string" },
          },
        },
      },
    },
  });
}

function pathParameter(name: string, description: string) {
  return {
    name,
    in: "path",
    required: true,
    description,
    schema: { type: "string" },
  };
}

function queryParameter(
  name: string,
  description: string,
  schema: Record<string, unknown>,
) {
  return { name, in: "query", required: false, description, schema };
}

function response(description: string, schema: Record<string, unknown>) {
  return { description, content: { "application/json": { schema } } };
}

function jsonRequestBody(description: string, schema: Record<string, unknown>) {
  return {
    required: true,
    content: { "application/json": { schema, description } },
  };
}

function errorResponses(
  statuses: string[],
): Record<string, ReturnType<typeof response>> {
  return Object.fromEntries(
    statuses.map((status) => [
      status,
      { ...response("Request failed", { $ref: "#/components/schemas/ApiError" }),
        ...(["429", "503"].includes(status) ? { headers: { "Retry-After": { description: "Seconds to wait when admission is refused.", schema: { type: "integer", minimum: 1 } } } } : {}),
      },
    ]),
  );
}

async function all(statement: D1PreparedStatement): Promise<Row[]> {
  const result = await statement.all<Row>();
  return result.results ?? [];
}

function json(
  payload: unknown,
  status = 200,
  extra: Record<string, string> = {},
): Response {
  return Response.json(payload, {
    status,
    headers: { ...CORS_HEADERS, ...extra },
  });
}

function object(value: unknown): Row {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Row)
    : {};
}

function string(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function number(value: unknown): number {
  const result = Number(value);
  return Number.isFinite(result) ? result : 0;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}
function isObject(value: unknown): value is Row {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function errorType(error: unknown): string {
  return error instanceof Error ? error.name : "UnknownError";
}

function failure(code: string, message: string, status: number): Response {
  return json({ error: code, message }, status);
}
