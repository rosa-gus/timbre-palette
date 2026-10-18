export type Rgb = [number, number, number];
export const fallbackTone = "#F29191";

export function parseHex(value: string): Rgb | null {
  const normalized = value.trim().replace(/^#/, "");
  if (!/^[0-9a-f]{6}$/i.test(normalized)) return null;
  return [
    Number.parseInt(normalized.slice(0, 2), 16),
    Number.parseInt(normalized.slice(2, 4), 16),
    Number.parseInt(normalized.slice(4, 6), 16),
  ];
}

export function mix(first: Rgb, second: Rgb, amount: number): Rgb {
  return first.map((value, index) =>
    Math.round(value + (second[index] - value) * amount),
  ) as Rgb;
}

export function hex(rgb: Rgb): string {
  return `#${rgb
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase()}`;
}

export function toneText(value: string): string {
  const base = parseHex(value) ?? parseHex(fallbackTone)!;
  return hex(mix(base, [0, 0, 0], 0.6));
}
