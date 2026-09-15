import "../styles/tokens/typography.css";
import type { FamilyPresence, PaletteReport } from "../api/types";
import { createShareImage } from "./share";
import { mountAsciiEditor } from "./editor";
import type { AsciiDrawings } from "./ascii";

function family(slug: string, name: string, share: number, color: string): FamilyPresence {
  return {
    slug, name, share, evidence_count: 12, confidence: "estimated", image: null,
    tone: { shadow: "#000000", highlight: color },
  };
}

const families = [
  family("plucked-strings", "Cordas dedilhadas", 0.32, "#e7ae87"),
  family("percussion", "Percussão", 0.32, "#d2c08d"),
  family("synthesizers", "Sintetizadores", 0.22, "#b6a3c4"),
  family("acoustic-keys", "Teclas acústicas", 0.14, "#f29191"),
];

const otherFamilies = [
  family("acoustic-keys", "Teclas acústicas", 1 / 3, "#F29191"),
  family("bowed-strings", "Cordas friccionadas", 1 / 3, "#A9C4AE"),
  family("sampled-sounds", "Sons sampleados", 1 / 3, "#9EBBD1"),
  family("woodwinds", "Madeiras", 1 / 3, "#9FC4B0"),
  family("brass", "Metais", 1 / 3, "#D9B56D"),
  family("voice", "Voz", 1 / 3, "#D6A8C8"),
  family("electric-keys", "Teclas elétricas e eletrônicas", 1 / 3, "#9FB7D9"),
];

const base: PaletteReport = {
  profile: { username: "demo", period: "7day", tracks_analyzed: 40, total_plays: 180 },
  analysis: {
    status: "partial", data_source: "mock", history_source: "mock",
    instrumentation_source: "mock", methodology_version: "preview",
    catalog_version: null, image_catalog_version: "preview",
    coverage_tracks: 0.5, coverage_plays: 0.6,
    recording_status_counts: {
      resolved: 20, pending_enrichment: 0, ambiguous: 0,
      resolved_without_evidence: 20, transient_failure: 0, terminal_failure: 0,
    },
    notice: "Dados demonstrativos para visualizar o retrato.",
    section_availability: {
      families: "available", sound_balance: "insufficient_nature_evidence",
      discovery: "no_candidate", temperament: "insufficient_coverage",
    },
    vocal_presence: {
      documented_tracks: 0, documented_artists: 0, documented_plays: 0,
      track_ratio: 0, play_ratio: 0,
    },
  },
  families, recordings: [], sound_balance: null, discovery: null, temperament: null,
};

const examples: { label: string; report: PaletteReport }[] = [
  {
    label: "Temperamento disponível",
    report: {
      ...base,
      temperament: {
        title: "Ressonância em primeiro plano",
        summary: "A presença de cordas dedilhadas conduz a paleta. A combinação recorrente valoriza presença física, ressonância e espaço, sem abandonar os contrastes trazidos pelas famílias menos presentes.",
        disclaimer: "Interpretação lúdica da escuta, sem avaliação psicológica ou científica.",
      },
    },
  },
  { label: "Retrato parcial", report: base },
  {
    label: "Uma família",
    report: { ...base, families: [{ ...families[0], share: 1 }] },
  },
];

for (let index = 0; index < otherFamilies.length; index += 3) {
  const group = otherFamilies.slice(index, index + 3);
  examples.push({
    label: group.map((item) => item.name).join(" · "),
    report: {
      ...base,
      families: group.map((item) => ({ ...item, share: 1 / group.length })),
      temperament: {
        title: "Outras cores da escuta",
        summary: "Emblemas das famílias instrumentais, na mesma grade e escala. Dados demonstrativos para comparar os desenhos.",
        disclaimer: "Interpretação lúdica da escuta.",
      },
    },
  });
}

async function renderPreview(): Promise<void> {
  const container = document.querySelector<HTMLElement>("#portraits");
  if (!container) return;
  if (!import.meta.env.DEV) {
    container.textContent = "Esta prévia está disponível apenas em desenvolvimento.";
    return;
  }
  const urls = new Map<number, string>();
  let revision = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let drawings: AsciiDrawings = {};
  const cards = examples.map((example, index) => {
    const section = document.createElement("section");
    const heading = document.createElement("h2");
    heading.textContent = example.label;
    const image = document.createElement("img");
    image.alt = `Retrato ASCII demonstrativo: ${example.label.toLocaleLowerCase("pt-BR")}`;
    image.width = 1200;
    image.height = 1500;
    const download = document.createElement("a");
    download.download = `portrait-preview-${index + 1}.png`;
    download.textContent = "Baixar PNG · 1200 × 1500";
    section.append(heading, image, download);
    return { section, image, download };
  });
  container.replaceChildren(...cards.map((card) => card.section));
  const gallery = container;
  async function refresh(): Promise<void> {
    const current = ++revision;
    try {
      for (const [index, example] of examples.entries()) {
        const blob = await createShareImage(example.report, drawings);
        if (current !== revision) return;
        const url = URL.createObjectURL(blob);
        const previous = urls.get(index);
        cards[index].image.src = url;
        cards[index].download.href = url;
        urls.set(index, url);
        if (previous) URL.revokeObjectURL(previous);
      }
    } catch {
      gallery.setAttribute("aria-label", "Não foi possível atualizar os retratos. Recarregue a página para tentar novamente.");
    }
  }
  const editor = document.querySelector<HTMLElement>("#ascii-editor");
  if (editor) {
    const allFamilies = [...new Map([...families, ...otherFamilies].map((item) => [item.slug, item])).values()];
    drawings = mountAsciiEditor(editor, allFamilies, (updated) => {
      drawings = updated;
      revision++;
      clearTimeout(timer);
      timer = setTimeout(() => { void refresh(); }, 150);
    });
  }
  window.addEventListener("pagehide", () => {
    revision++;
    clearTimeout(timer);
    urls.forEach((url) => URL.revokeObjectURL(url));
  }, { once: true });
  await refresh();

}

void renderPreview();
