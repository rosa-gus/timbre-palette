import type { AnalysisImage, AnalysisSummary, Discovery, PaletteReport } from "../api/types";
import { locale, t } from "../i18n/runtime";

export function getAnalysisNotice(analysis: AnalysisSummary): string {
  const source = analysis.history_source === "lastfm"
    ? analysis.instrumentation_source === "catalog"
      ? t("narrative.notice.lastfmCatalog") : t("narrative.notice.lastfmMock")
    : analysis.instrumentation_source === "catalog"
      ? t("narrative.notice.exampleCatalog") : t("narrative.notice.mock");
  return analysis.status === "insufficient"
    ? t("narrative.notice.insufficient", { source })
    : analysis.status === "partial" ? t("narrative.notice.partial", { source }) : source;
}

export function getDiscoveryCopy(discovery: Discovery): { title: string; summary: string } {
  const instrument = discovery.instrument_name;
  return {
    title: t("narrative.discovery.title", { instrument }),
    summary: t("narrative.discovery.summary", { instrument }),
  };
}

export function getImageCopy(image: AnalysisImage): { alt: string; caption: string; label: string } {
  const instrument = image.depicted_name;
  const caption = image.resolution === "family"
    ? t("narrative.image.family", { family: image.family_name, instrument })
    : t(`narrative.image.${image.resolution}`, { instrument });
  return {
    alt: image.alt ?? t("narrative.image.alt", { instrument }),
    caption,
    label: image.resolution === "related" ? caption : `${instrument}.`,
  };
}

/** Render the same structured selection for screen and exported portrait. */
export function getPortraitCopy(report: PaletteReport): { title: string; summary: string; disclaimer: string } {
  const family = report.families.find((item) => item.slug === report.temperament?.primary_family_slug);
  if (report.temperament && family) {
    const temperament = report.temperament;
    return {
      title: t(`narrative.temperament.${temperament.rule}.title`),
      summary: t(`narrative.temperament.${temperament.rule}.summary`, { family: family.name.toLocaleLowerCase(locale) }),
      disclaimer: t("narrative.temperament.disclaimer"),
    };
  }
  const names = report.families.slice(0, 3).map((family) => family.name);
  const families = new Intl.ListFormat(locale, { style: "long", type: "conjunction" }).format(names);
  const disclaimer = t("narrative.portrait.disclaimer");
  if (!names.length) return {
    title: t("narrative.portrait.emptyTitle"), summary: t("narrative.portrait.emptySummary"), disclaimer,
  };
  if (names.length === 1) return {
    title: t("narrative.portrait.singleTitle", { families: families.toLocaleLowerCase(locale) }),
    summary: t("narrative.portrait.singleSummary", { families: families.toLocaleLowerCase(locale) }), disclaimer,
  };
  return { title: t("narrative.portrait.title", { families }), summary: t("narrative.portrait.summary", { families }), disclaimer };
}
