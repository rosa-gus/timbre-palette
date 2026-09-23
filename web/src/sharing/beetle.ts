// A beetle drawn with JSON-compatible string escapes, centered in the avatar grid.
export const HERCULES_BEETLE_SLUG = "example-beetle";

const beetleDrawing = [
  "      _   _          ",
  "     /(   )\\        ",
  "     \\(   )/        ",
  "   |/ \\\\_//  \\|     ",
  "  /  (^) (^)  \\     ",
  "  \\  /     \\  /     ",
  "   \\ \\_____/ /      ",
  "    \\/  |  \\/       ",
  "  _ |   |   | _     ",
  " | \\|   |   |/ |    ",
  " |  |   |   |  |    ",
  "/|\\ |   |   | /|\\   ",
  "    \\   |   /       ",
  "    /\\__|__/\\       ",
  "   /         \\      ",
  "   \\         /      ",
  "   |\\       /|      "
];

const trimmedLines = beetleDrawing.map((line) => line.trimEnd());
const indent = Math.min(
  ...trimmedLines.map((line) => line.search(/\S/)).filter((column) => column >= 0),
);
const width = Math.max(...trimmedLines.map((line) => line.length)) - indent;
const padding = " ".repeat(Math.max(0, Math.floor((20 - width) / 2)));

export const HERCULES_BEETLE_LINES = trimmedLines.map((line) =>
  (padding + line.slice(indent)).padEnd(20, " "),
);

export const HERCULES_BEETLE_ASCII = HERCULES_BEETLE_LINES.join("\n");
