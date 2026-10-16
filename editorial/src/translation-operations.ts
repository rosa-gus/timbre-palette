import { emptyReview, localizedText, sourceRevision, type Sheet, type Translation, type Translations } from "./content";

type Context = { sheet: Sheet; locale: string; translations: Translations };
type Revision = (sheet: Sheet) => Promise<string>;

export function resetTranslationReview(item: Translation): void {
  if (item.status !== "deprecated") item.status = "draft";
  item.review = emptyReview();
  item.sections.forEach((block) => { block.status = "draft"; block.review = emptyReview(); });
}

/** Prepare a snapshot; commit only while its selection and source are unchanged. */
export async function startTranslation(
  { sheet, locale, translations }: Context,
  isCurrent: () => boolean,
  revision: Revision = sourceRevision,
): Promise<boolean> {
  if (translations[locale]?.some((item) => item.slug === sheet.resource.slug)) return false;
  const before = JSON.stringify(sheet);
  const source = structuredClone(sheet);
  const draft = structuredClone(localizedText(source));
  draft.source_revision = await revision(source);
  if (!isCurrent() || JSON.stringify(sheet) !== before ||
      translations[locale]?.some((item) => item.slug === source.resource.slug)) return false;
  resetTranslationReview(draft);
  translations[locale] = [...(translations[locale] ?? []), draft];
  return true;
}

/** Rebase atomically so cancellation never leaves partially changed text or review. */
export async function rebaseTranslation(
  { sheet, locale, translations }: Context,
  isCurrent: () => boolean,
  revision: Revision = sourceRevision,
): Promise<boolean> {
  const target = translations[locale]?.find((item) => item.slug === sheet.resource.slug);
  if (!target) return false;
  const beforeSource = JSON.stringify(sheet), beforeTarget = JSON.stringify(target);
  const source = structuredClone(sheet), draft = structuredClone(target);
  draft.sections = source.resource.sections.map((block) => ({
    id: block.id, text: draft.sections.find((item) => item.id === block.id)?.text ?? block.text,
    status: "draft", review: emptyReview(),
  }));
  if (source.resource.image?.asset_id !== draft.image?.asset_id)
    draft.image = structuredClone(localizedText(source).image);
  draft.source_revision = await revision(source);
  if (!isCurrent() || JSON.stringify(sheet) !== beforeSource || JSON.stringify(target) !== beforeTarget ||
      translations[locale]?.find((item) => item.slug === source.resource.slug) !== target) return false;
  resetTranslationReview(draft);
  Object.assign(target, draft);
  return true;
}
