import manifest from "../content/catalog.json";
import entities from "../content/entities.json";
import sources from "../content/sources.json";
import type { InstrumentResource, InstrumentImage, EditorialReview, EditorialSection, EditorialSource, FurtherReading } from "../../web/src/api/types";

export type Reading = FurtherReading & { status: "draft" | "reviewed" | "published"; reviewer: string | null; reviewed_at: string | null };
export type Sheet = { resource: Omit<InstrumentResource, "further_reading"> & { further_reading: Reading[] }; review: EditorialReview; text_citations: { description: string[]; sound_production: string[] } };
const neutralFields = ["data_source", "catalog_version", "image_catalog_version", "slug", "kind", "family_slug", "related_slugs", "tone"] as const;
type Entity = Pick<InstrumentResource, typeof neutralFields[number]> & {
  source_ids: string[]; text_citations: Sheet["text_citations"]; further_reading: Reading[];
  sections: Omit<EditorialSection, "text" | "status" | "review">[];
  image: Omit<InstrumentImage, "alt" | "caption"> | null;
};
export type Translation = Pick<InstrumentResource, "slug" | "name" | "description" | "sound_production" | "common_roles"> & {
  sections: Pick<EditorialSection, "id" | "text" | "status" | "review">[];
  image: Pick<InstrumentImage, "asset_id" | "alt" | "caption"> | null;
  review: EditorialReview;
  status: "draft" | "reviewed" | "published" | "deprecated" | "stale";
  source_revision?: string;
};
export type Translations = Record<string, Translation[]>;
export type Snapshot = { schema_version: 2; source_locale: "pt-BR"; entities: Entity[]; sources: EditorialSource[]; locales: Translations };

const files = import.meta.glob<Translation[]>("../content/locales/*.json", { eager: true, import: "default" });
const locales = Object.fromEntries(Object.entries(manifest.locales).map(([locale, path]) => [locale, files[`../content/${path}`]]));
export const initialSnapshot = { schema_version: 2, source_locale: "pt-BR", entities, sources, locales } as Snapshot;

export function sourceSheets(snapshot: Snapshot): Sheet[] {
  return snapshot.entities.map((entity) => {
    const text = snapshot.locales["pt-BR"].find((item) => item.slug === entity.slug)!;
    return {
      resource: { ...Object.fromEntries(neutralFields.map((field) => [field, entity[field]])),
        name: text.name, description: text.description, sound_production: text.sound_production, common_roles: text.common_roles,
        sections: entity.sections.map((block) => ({ ...block, ...text.sections.find((item) => item.id === block.id)! })),
        sources: entity.source_ids.map((id) => snapshot.sources.find((source) => source.id === id)!),
        further_reading: entity.further_reading,
        image: entity.image && text.image ? { ...entity.image, ...text.image } : null,
      } as Sheet["resource"], review: text.review, text_citations: entity.text_citations,
    };
  });
}

export function localizedText(sheet: Sheet): Translation {
  const resource = sheet.resource;
  return { slug: resource.slug, name: resource.name, description: resource.description,
    sound_production: resource.sound_production, common_roles: resource.common_roles,
    sections: resource.sections.map(({ id, text, status, review }) => ({ id, text, status, review })),
    image: resource.image ? { asset_id: resource.image.asset_id, alt: resource.image.alt, caption: resource.image.caption } : null,
    review: sheet.review, status: sheet.review.claim_support_verified ? "published" : "draft" };
}

export function snapshotFromSheets(sheets: Sheet[], translations: Translations): Snapshot {
  const sources = new Map<string, EditorialSource>();
  const entities = sheets.map(({ resource, text_citations }) => {
    resource.sources.forEach((source) => sources.set(source.id, source));
    const image = resource.image ? { ...resource.image } : null;
    if (image) { Reflect.deleteProperty(image, "alt"); Reflect.deleteProperty(image, "caption"); }
    return { ...Object.fromEntries(neutralFields.map((field) => [field, resource[field]])),
      image, source_ids: resource.sources.map(({ id }) => id), text_citations, further_reading: resource.further_reading,
      sections: resource.sections.map(({ id, kind, content_type, citations }) => ({ id, kind, content_type, citations })),
    } as Entity;
  });
  return { schema_version: 2, source_locale: "pt-BR", entities, sources: [...sources.values()],
    locales: { ...translations, "pt-BR": sheets.map(localizedText) } };
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
    .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  return JSON.stringify(value);
}

export async function sourceRevision(sheet: Sheet): Promise<string> {
  // Hash only source content, using the publisher's canonical JSON representation.
  const normalized = sourceSheets(snapshotFromSheets([sheet], {}))[0];
  const omitDerivedFlag = (review: EditorialReview) => Reflect.deleteProperty(review, "source_metadata_verified");
  normalized.review = { ...normalized.review };
  omitDerivedFlag(normalized.review);
  normalized.resource.sections = normalized.resource.sections.map((block) => {
    const review = { ...block.review };
    omitDerivedFlag(review);
    return { ...block, review };
  });
  const bytes = new TextEncoder().encode(canonical(normalized));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export const emptyReview = (): EditorialReview => ({ source_metadata_verified: false, claim_support_verified: false,
  reviewer: null, reviewed_at: null, editorial_note: null });
