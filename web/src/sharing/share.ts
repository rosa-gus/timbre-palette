import type { PaletteReport } from "../api/types";
import { getPortraitCopy } from "../portrait";
import { createAsciiArtwork, type AsciiDrawings } from "./ascii";

const monthLabels = [
  "JAN.",
  "FEV.",
  "MAR.",
  "ABR.",
  "MAI.",
  "JUN.",
  "JUL.",
  "AGO.",
  "SET.",
  "OUT.",
  "NOV.",
  "DEZ.",
];

function currentDateLabel(date = new Date()): string {
  return `${date.getDate()} DE ${monthLabels[date.getMonth()]} ${date.getFullYear()}`;
}

function shortPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function drawWrappedText(
  context: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
): number {
  const words = text.split(" ");
  let line = "";
  let currentY = y;
  for (const word of words) {
    const nextLine = line ? `${line} ${word}` : word;
    if (context.measureText(nextLine).width > maxWidth && line) {
      context.fillText(line, x, currentY);
      line = word;
      currentY += lineHeight;
    } else {
      line = nextLine;
    }
  }
  if (line) context.fillText(line, x, currentY);
  return currentY + lineHeight;
}

function drawTextBlock(
  context: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  width: number,
  height: number,
  maxSize: number,
  minSize: number,
  family: string,
): number {
  // Fit the full copy inside its region, including long editorial titles.
  let size = maxSize;
  let end = 0;
  do {
    context.font = `500 ${size}px '${family}', sans-serif`;
    context.save();
    context.globalAlpha = 0;
    end = drawWrappedText(context, text, x, y + size, width, size * 1.15);
    context.restore();
    if (end <= y + height || size <= minSize) break;
    size -= 2;
  } while (size >= minSize);
  const nextLineY = drawWrappedText(
    context,
    text,
    x,
    y + size,
    width,
    size * 1.15,
  );
  // Last baseline plus descender space, rather than the reserved region height.
  return nextLineY - size * 1.15 + size * 0.2;
}

export async function createShareImage(
  report: PaletteReport,
  drawings?: AsciiDrawings,
): Promise<Blob> {
  await document.fonts.ready;
  const portrait = getPortraitCopy(report);
  const canvas = document.createElement("canvas");
  canvas.width = 1200;
  canvas.height = 1500;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas indisponível");
  const accent = report.families[0]?.tone?.highlight ?? "#F29191";
  const periodLabels: Record<string, string> = {
    "7day": "7 dias",
    "1month": "1 mês",
    "3month": "3 meses",
    "6month": "6 meses",
    "12month": "12 meses",
    overall: "Histórico",
  };
  context.fillStyle = "#000000";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = accent;
  context.fillRect(72, 66, 30, 10);
  context.fillStyle = "#b5adaa";
  context.font = "500 20px 'IBM Plex Mono', monospace";
  context.fillText(`${currentDateLabel()} / PALETA INSTRUMENTAL`, 120, 82);
  context.fillStyle = "#f3efec";
  context.font = "400 24px 'IBM Plex Mono', monospace";
  context.fillText(
    `@${report.profile.username} / ${periodLabels[report.profile.period] ?? report.profile.period}`,
    72,
    140,
    1056,
  );
  context.fillStyle = "#f3efec";
  const titleBottom = drawTextBlock(
    context,
    portrait.title,
    72,
    186,
    1056,
    270,
    84,
    36,
    "Instrument Sans",
  );
  context.fillStyle = "#b5adaa";
  const summaryY = titleBottom + 32;
  drawTextBlock(
    context,
    portrait.summary,
    72,
    summaryY,
    1056,
    Math.min(158, 630 - summaryY),
    30,
    20,
    "Instrument Sans",
  );

  // Each drawing sits with its own label, on the same horizontal stage.
  const artwork = createAsciiArtwork(report.families, drawings);
  const gap = 40;
  const slotWidth =
    (1056 - gap * Math.max(0, artwork.length - 1)) /
    Math.max(1, artwork.length);
  artwork.forEach((item, index) => {
    const x = 72 + index * (slotWidth + gap);
    const center = x + slotWidth / 2;
    const fontSize = Math.min(
      36,
      slotWidth / (item.columns * 0.6),
      350 / (item.lines.length * 0.95),
    );
    const lineHeight = fontSize * 0.95;
    context.font = `500 ${fontSize}px 'IBM Plex Mono', monospace`;
    const drawingWidth = context.measureText(item.lines[0]).width;
    const top = 858 - (item.lines.length * lineHeight) / 2;
    context.fillStyle = item.color;
    item.lines.forEach((line, row) => {
      context.fillText(
        line,
        center - drawingWidth / 2,
        top + (row + 1) * lineHeight,
      );
    });
    context.fillRect(x, 1074, slotWidth, 3);
    context.font = "400 20px 'IBM Plex Mono', monospace";
    context.fillText(String(index + 1).padStart(2, "0"), x, 1114);
    context.fillStyle = "#f3efec";
    drawTextBlock(
      context,
      item.family.name,
      x,
      1130,
      slotWidth,
      84,
      30,
      22,
      "Instrument Sans",
    );
    context.fillStyle = item.color;
    context.font = "500 38px 'IBM Plex Mono', monospace";
    context.fillText(shortPercent(item.family.share), x, 1240);
  });

  const total = report.families.reduce((sum, family) => sum + family.share, 0);
  let stripX = 72;
  report.families.forEach((family) => {
    const width = total > 0 ? (family.share / total) * 1056 : 0;
    context.fillStyle = family.tone?.highlight ?? accent;
    context.fillRect(stripX, 1270, Math.max(0, width - 3), 18);
    stripX += width;
  });
  context.fillStyle = "#b5adaa";
  context.font = "400 21px 'Instrument Sans', sans-serif";
  context.fillText(
    "Interpretação lúdica da escuta, não teste de personalidade.",
    72,
    1338,
  );
  const partial =
    report.analysis.coverage_tracks < 1 || report.analysis.coverage_plays < 1;
  context.fillText(
    `${partial ? "Retrato parcial · " : ""}Informação instrumental em ${shortPercent(report.analysis.coverage_tracks)} das faixas analisadas.`,
    72,
    1370,
  );
  if (report.analysis.data_source !== "catalog") {
    context.fillText(
      report.analysis.data_source === "mock"
        ? "Dados demonstrativos."
        : "Histórico real com instrumentação demonstrativa.",
      72,
      1402,
    );
  }
  context.fillStyle = accent;
  context.font = "400 20px 'IBM Plex Mono', monospace";
  const address = new URL(window.location.href);
  context.fillText(
    `TIMBRE PALETTE / ${address.host}${address.pathname === "/" ? "" : address.pathname}`,
    72,
    1450,
    1056,
  );
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) =>
        blob
          ? resolve(blob)
          : reject(new Error("Não foi possível gerar a imagem")),
      "image/png",
    );
  });
}

export function downloadShareImage(blob: Blob, username: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `paleta-${username.toLowerCase().replace(/[^a-z0-9]+/gi, "-") || "escuta"}.png`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
