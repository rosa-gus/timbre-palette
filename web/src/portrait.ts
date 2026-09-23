import type { PaletteReport } from "./api/types";

interface PortraitCopy {
  title: string;
  summary: string;
  disclaimer: string;
}

function listNames(names: string[]): string {
  if (names.length < 2) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} e ${names.at(-1)}`;
}

/** Describe available evidence without manufacturing a temperament. */
export function getPortraitCopy(report: PaletteReport): PortraitCopy {
  if (report.temperament) return report.temperament;

  const families = report.families.slice(0, 3);
  const names = listNames(families.map((family) => family.name));
  const disclaimer =
    "Uma interpretação lúdica da escuta, não uma avaliação psicológica ou científica da personalidade.";

  if (!families.length) {
    return {
      title: "Sua escuta ainda não ganhou uma paleta.",
      summary:
        "Encontramos seu histórico, mas não informações instrumentais suficientes para compor este retrato.",
      disclaimer,
    };
  }

  if (families.length === 1) {
    return {
      title: `Um primeiro retrato: ${names.toLocaleLowerCase("pt-BR")}.`,
      summary: `Nas faixas com informação instrumental disponível, encontramos ${names.toLocaleLowerCase("pt-BR")}.`,
      disclaimer,
    };
  }

  return {
    title: `${names}.`,
    summary:
      `${names} são as famílias mais presentes nas faixas com informação instrumental disponível.`,
    disclaimer,
  };
}
