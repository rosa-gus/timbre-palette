import type { FamilyPresence } from "../api/types";

export const ASCII_COLUMNS = 20;
export const ASCII_ROWS = 17;

interface AsciiFigure {
  lines: string[];
}

export type AsciiDrawings = Record<string, readonly string[]>;

// Family emblems, rather than claims about a specific recorded instrument.
const figures: Record<string, AsciiFigure> = {
  "plucked-strings": {
    lines: [
      "         ++++",
      "         +##+",
      "         +||+",
      "         +||+",
      "         +||+",
      "         +||+",
      "      .++####++.",
      "    .+##########+.",
      "   +####++||++####+",
      "  +####   ||   ####+",
      "  ####    ||    ####",
      "  ####    ++    ####",
      "  +####        ####+",
      "   +####++++++####+",
      "    +############+",
      "      .++++++++.",
      "         ....",
    ],
  },
  percussion: {
    lines: [
      "                /",
      "               /",
      "              /",
      "             /",
      "            /",
      "         .--.",
      "     _.-'    '-._",
      ".--'____________'--.",
      "'---------+--------'",
      "          |",
      "          |",
      "          |",
      "          |",
      "          |",
      "         /|\\",
      "        / | \\",
      "       /  |  \\",
    ],
  },
  synthesizers: {
    lines: [
      "+------------------+",
      "| .--------. O O O |",
      "| | /\\ /\\  |       |",
      "| '--------' O O O |",
      "|                  |",
      "| O O O   |  |  |  |",
      "|         =  |  =  |",
      "| [1][2]  |  =  |  |",
      "+--+---------------+",
      "|  | |#|#| |#|#|#| |",
      "|= | |#|#| |#|#|#| |",
      "|= | |#|#| |#|#|#| |",
      "|  | | | | | | | | |",
      "|  | | | | | | | | |",
      "|__|_|_|_|_|_|_|_|_|",
      "+------------------+",
      "  [__]        [__]  ",
    ],
  },
  "acoustic-keys": {
    lines: [
      "    +-----------.",
      "    |            \\",
      "    |             |",
      "    |             |",
      "    |             /",
      "    |          .-'",
      "    |        .'",
      "    |       /",
      "    |      |",
      "    |      |",
      "    +------'-------+",
      "    |              |",
      "    +--------------+",
      "    | |#|#| |#|#|  |",
      "    | |#|#| |#|#|  |",
      "    | | | | | | |  |",
      "    |_|_|_|_|_|_|__|",
    ],
  },
  "bowed-strings": {
    lines: [
      "         +++     /  ",
      "         +|+    /   ",
      "         +|+   /    ",
      "         +|+  /     ",
      "      .++|||+/      ",
      "     +###|||/#+     ",
      "    +####||/###+    ",
      "     +###|/###+     ",
      "      }##/###{      ",
      "      }#/|###{      ",
      "     +#/||####+     ",
      "    +#/||| ####++   ",
      "   +#/ ||| f ####+  ",
      "   +/##===#######+  ",
      "   /+###########+   ",
      "  /   .+++++++.     ",
      " /       ||         ",
    ],
  },
  "sampled-sounds": {
    lines: [
      "+------------------+",
      "|                  |",
      "|    .-----.   [O] |",
      "|  .'       '.  |  |",
      "| /  .-----.  \\ |  |",
      "| | /       \\ | |  |",
      "| | |   o   | | |  |",
      "| | \\       / | |  |",
      "| \\  '-----'  / /  |",
      "|  '.       .' /   |",
      "|    '-----'  /    |",
      "|           [V]    |",
      "|                  |",
      "| [33/45]  O  [>]  |",
      "|__________________|",
      "|__________________|",
      "  [__]        [__]  ",
    ],
  },
  woodwinds: {
    lines: [
      "   ___              ",
      "  /___)             ",
      "     |\\             ",
      "     ||             ",
      "     |O             ",
      "     ||             ",
      "     |O             ",
      "     ||             ",
      "     |O             ",
      "     ||       ---.  ",
      "     |O     /    /  ",
      "     ||     /    /  ",
      "     |O    /    /   ",
      "     ||   /    /    ",
      "     \\ \\_/    /     ",
      "      \\      /      ",
      "       '----'       ",
    ],
  },
  brass: {
    lines: [
      "                  .|",
      "                 / |",
      "                /  |",
      "     O O O     /   |",
      "     | | |    /    |",
      "     | | |   /     |",
      "     | | |__/      |",
      "=>===+=+=+=========|",
      "  .--| | |--.      |",
      "  |  | | |  |      |",
      "  |  | | |  |\\     |",
      "  |  | | |  | \\    |",
      "  |  '---'  |  \\   |",
      "  '---------'   \\  |",
      "                 \\ |",
      "                  .|",
      "                   '",
    ],
  },
  voice: {
    lines: [
      "      .------.",
      "    .'########'.",
      "   /############\\",
      "  |##############|",
      "  |##############|",
      "  |##############|",
      "   \\############/",
      "    '----------'",
      "    |    O     |",
      "    |          |",
      "    +----------+",
      "         ||",
      "         ||",
      "         ||",
      "         ||",
      "     ____||____",
      "    /__________\\",
    ],
  },
  "electric-keys": {
    lines: [
      "   .---------------.",
      "  / O O   [::]    /|",
      " /_______________/ |",
      "/ |#|#| |#|#|#| /  |",
      "| |#|#| |#|#|#| |  /",
      "| |#|#| |#|#|#| | /",
      "| | | | | | | | |/",
      "|_|_|_|_|_|_|_|_|",
      "'---------------'",
      "   \\         /",
      "    \\       /",
      "     \\     /",
      "      \\   /",
      "       \\ /",
      "        X",
      "       / \\",
      "   ___/   \\___",
    ],
  },
};

export function getAsciiLines(slug: string): string[] {
  const figure = figures[slug] ?? {
    lines: Array.from({ length: ASCII_ROWS }, () => ": + : + : + : + : + "),
  };
  const indent = Math.min(
    ...figure.lines
      .map((line) => line.search(/\S/))
      .filter((value) => value >= 0),
  );
  const cropped = figure.lines.map((line) => line.slice(indent));
  const columns = Math.max(...cropped.map((line) => line.length));
  return cropped.map((line) =>
    (
      " ".repeat(Math.max(0, Math.floor((ASCII_COLUMNS - columns) / 2))) + line
    ).padEnd(ASCII_COLUMNS, " "),
  );
}

/** Independent specimens, ordered to match their family labels. */
export function createAsciiArtwork(
  families: FamilyPresence[],
  drawings: AsciiDrawings = {},
) {
  return families.slice(0, 3).map((family) => {
    return {
      family,
      columns: ASCII_COLUMNS,
      color: family.tone?.highlight ?? "#F29191",
      lines: drawings[family.slug] ?? getAsciiLines(family.slug),
    };
  });
}
