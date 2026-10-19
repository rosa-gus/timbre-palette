import type {
  AnalysisImage,
  AnalysisSummary,
  Discovery,
  PaletteReport,
} from "../api/types";
import { locale, type Locale } from "../i18n/runtime";
import { createTranslator } from "../i18n/translator";
import { fallbackLocale } from "../../../shared/i18n/locales.mjs";
import { narrativesCatalogs as catalogs } from "../i18n/presentation-catalogs.generated";

export function getAnalysisNotice(
  analysis: AnalysisSummary,
  language: Locale = locale,
): string {
  const t = createTranslator(
    catalogs[language],
    catalogs[fallbackLocale],
    language,
  );
  const source =
    analysis.history_source === "lastfm"
      ? analysis.instrumentation_source === "catalog"
        ? t("narrative.notice.lastfmCatalog")
        : t("narrative.notice.lastfmMock")
      : analysis.instrumentation_source === "catalog"
        ? t("narrative.notice.exampleCatalog")
        : t("narrative.notice.mock");
  return analysis.status === "insufficient"
    ? t("narrative.notice.insufficient", { source })
    : analysis.status === "partial"
      ? t("narrative.notice.partial", { source })
      : source;
}

export function getDiscoveryCopy(
  discovery: Discovery,
  language: Locale = locale,
): { title: string; summary: string } {
  const t = createTranslator(
    catalogs[language],
    catalogs[fallbackLocale],
    language,
  );
  const instrument = discovery.instrument_name;
  return {
    title: t("narrative.discovery.title", { instrument }),
    summary: t("narrative.discovery.summary", { instrument }),
  };
}

export function getImageCopy(
  image: AnalysisImage,
  language: Locale = locale,
): { alt: string; caption: string; label: string } {
  const t = createTranslator(
    catalogs[language],
    catalogs[fallbackLocale],
    language,
  );
  const instrument = image.depicted_name;
  const caption =
    image.resolution === "family"
      ? t("narrative.image.family", { family: image.family_name, instrument })
      : t(`narrative.image.${image.resolution}`, { instrument });
  return {
    alt: image.alt ?? t("narrative.image.alt", { instrument }),
    caption,
    label: image.resolution === "related" ? caption : `${instrument}.`,
  };
}

/** Render the same structured selection for screen and exported portrait. */
export function getPortraitCopy(
  report: PaletteReport,
  language: Locale = locale,
): { title: string; summary: string; disclaimer: string } {
  const t = createTranslator(
    catalogs[language],
    catalogs[fallbackLocale],
    language,
  );
  const family = report.families.find(
    (item) => item.slug === report.temperament?.primary_family_slug,
  );
  if (report.temperament && family) {
    const temperament = report.temperament;
    return {
      title: t(`narrative.temperament.${temperament.rule}.title`),
      summary: t(`narrative.temperament.${temperament.rule}.summary`, {
        family: family.name.toLocaleLowerCase(language),
      }),
      disclaimer: t("narrative.temperament.disclaimer"),
    };
  }
  const names = report.families.slice(0, 3).map((family) => family.name);
  const families = new Intl.ListFormat(language, {
    style: "long",
    type: "conjunction",
  }).format(names);
  const disclaimer = t("narrative.portrait.disclaimer");
  if (!names.length)
    return {
      title: t("narrative.portrait.emptyTitle"),
      summary: t("narrative.portrait.emptySummary"),
      disclaimer,
    };
  if (names.length === 1)
    return {
      title: t("narrative.portrait.singleTitle", {
        families: families.toLocaleLowerCase(language),
      }),
      summary: t("narrative.portrait.singleSummary", {
        families: families.toLocaleLowerCase(language),
      }),
      disclaimer,
    };
  return {
    title: t("narrative.portrait.title", { families }),
    summary: t("narrative.portrait.summary", { families }),
    disclaimer,
  };
}
