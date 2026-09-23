import type { FamilyPresence } from "../api/types";
import { ASCII_COLUMNS, ASCII_ROWS, getAsciiLines, type AsciiDrawings } from "./ascii";
import { getStorageItem, setStorageItem, storageKey } from "../storage";

const asciiEditorStorageKey = storageKey("sharing", "ascii-editor");
const mirrored: Record<string, string> = {
  "/": "\\", "\\": "/", "(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{",
};

export function mountAsciiEditor(
  container: HTMLElement,
  families: FamilyPresence[],
  onChange: (drawings: AsciiDrawings) => void,
): AsciiDrawings {
  const drawings: AsciiDrawings = {};
  try {
    const saved = getStorageItem<unknown>(asciiEditorStorageKey);
    if (saved && typeof saved === "object") {
      for (const family of families) {
        const lines = (saved as Record<string, unknown>)[family.slug];
        if (Array.isArray(lines) && lines.length === ASCII_ROWS &&
          lines.every((line) => typeof line === "string" && line.length === ASCII_COLUMNS && /^[\x20-\x7e]*$/.test(line))) {
          drawings[family.slug] = lines;
        }
      }
    }
  } catch {
    // Editing also works when browser storage is unavailable.
  }
  container.hidden = false;
  container.className = "editor";
  container.innerHTML = `
    <h2>Editor de desenhos · 20 × 17</h2>
    <p>Clique ou arraste para desenhar. O eixo central ajuda a alinhar as duas metades. As edições ficam salvas neste navegador; copie as linhas para incorporá-las ao código.</p>
    <div class="editor-toolbar">
      <label>Desenho<select id="editor-family"></select></label>
      <label>Caractere<input id="editor-character" class="editor-character" value="#" maxlength="1" aria-label="Caractere para desenhar" /></label>
      <label class="editor-toggle"><input id="editor-erase" type="checkbox" /> Borracha</label>
      <label class="editor-toggle"><input id="editor-mirror" type="checkbox" /> Espelhar horizontalmente</label>
    </div>
    <div class="editor-body">
      <div class="editor-grid" aria-label="Grade de desenho"></div>
      <div>
        <label for="editor-output">ASCII do desenho</label>
        <textarea id="editor-output" class="editor-output" readonly spellcheck="false"></textarea>
        <div class="editor-actions">
          <button id="editor-copy">Copiar ASCII</button>
          <button id="editor-copy-code">Copiar linhas para o código</button>
          <button id="editor-undo" aria-keyshortcuts="Control+Z Meta+Z" title="Desfazer (Ctrl+Z)" disabled>Desfazer</button>
          <button id="editor-reset">Restaurar original</button>
        </div>
        <p class="editor-status" role="status"></p>
      </div>
    </div>`;
  const select = container.querySelector<HTMLSelectElement>("#editor-family")!;
  const character = container.querySelector<HTMLInputElement>("#editor-character")!;
  const erase = container.querySelector<HTMLInputElement>("#editor-erase")!;
  const mirror = container.querySelector<HTMLInputElement>("#editor-mirror")!;
  const grid = container.querySelector<HTMLElement>(".editor-grid")!;
  const output = container.querySelector<HTMLTextAreaElement>("#editor-output")!;
  const status = container.querySelector<HTMLElement>(".editor-status")!;
  const undo = container.querySelector<HTMLButtonElement>("#editor-undo")!;
  families.forEach((family) => select.add(new Option(family.name, family.slug)));
  let lines: string[] = [];
  let history: string[][] = [];
  let pointer: number | null = null;
  let changed = false;
  const cells: HTMLButtonElement[] = [];
  for (let row = 0; row < ASCII_ROWS; row++) {
    for (let column = 0; column < ASCII_COLUMNS; column++) {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "editor-cell";
      cell.dataset.row = String(row);
      cell.dataset.column = String(column);
      grid.append(cell);
      cells.push(cell);
    }
  }

  function display(): void {
    cells.forEach((cell) => {
      const row = Number(cell.dataset.row);
      const column = Number(cell.dataset.column);
      const value = lines[row][column];
      cell.textContent = value === " " ? "·" : value;
      cell.style.opacity = value === " " ? ".4" : "1";
      cell.setAttribute("aria-label", `Linha ${row + 1}, coluna ${column + 1}: ${value === " " ? "vazio" : value}`);
    });
    output.value = lines.join("\n");
    undo.disabled = history.length === 0;
  }

  function save(): void {
    drawings[select.value] = [...lines];
    if (setStorageItem(asciiEditorStorageKey, drawings)) {
      status.textContent = "Edição salva neste navegador. Prévia atualizada abaixo.";
    } else {
      status.textContent = "Prévia atualizada. Copie o desenho para guardá-lo; o armazenamento local está indisponível.";
    }
    display();
    onChange(drawings);
  }

  function load(): void {
    lines = [...(drawings[select.value] ?? getAsciiLines(select.value))];
    history = [];
    pointer = null;
    const family = families.find((item) => item.slug === select.value)!;
    grid.style.setProperty("--drawing-tone", family.tone?.highlight ?? "#F29191");
    status.textContent = "";
    display();
  }

  function remember(): void {
    history.push([...lines]);
    if (history.length > 40) history.shift();
  }

  function paint(cell: HTMLButtonElement): void {
    const value = erase.checked ? " " : character.value;
    if (value.length !== 1 || !/^[\x20-\x7e]$/.test(value)) {
      status.textContent = "Escolha um caractere ASCII: letra, número, símbolo ou espaço.";
      return;
    }
    const row = Number(cell.dataset.row);
    const column = Number(cell.dataset.column);
    const chars = lines[row].split("");
    chars[column] = value;
    if (mirror.checked) chars[ASCII_COLUMNS - 1 - column] = mirrored[value] ?? value;
    const line = chars.join("");
    if (line === lines[row]) return;
    lines[row] = line;
    changed = true;
    save();
  }

  grid.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || pointer !== null) return;
    const cell = (event.target as Element).closest<HTMLButtonElement>(".editor-cell");
    if (!cell) return;
    event.preventDefault();
    cell.focus();
    pointer = event.pointerId;
    changed = false;
    remember();
    grid.setPointerCapture(event.pointerId);
    paint(cell);
  });
  grid.addEventListener("pointermove", (event) => {
    if (pointer !== event.pointerId) return;
    const cell = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLButtonElement>(".editor-cell");
    if (cell && grid.contains(cell)) paint(cell);
  });
  function finish(event: PointerEvent): void {
    if (pointer !== event.pointerId) return;
    pointer = null;
    if (!changed) history.pop();
    display();
  }
  grid.addEventListener("pointerup", finish);
  grid.addEventListener("pointercancel", finish);
  grid.addEventListener("click", (event) => {
    if (event.detail !== 0) return;
    const cell = (event.target as Element).closest<HTMLButtonElement>(".editor-cell");
    if (!cell) return;
    remember();
    changed = false;
    paint(cell);
    if (!changed) history.pop();
    display();
  });
  select.addEventListener("change", load);
  function undoLastChange(): void {
    if (pointer !== null) {
      if (grid.hasPointerCapture(pointer)) grid.releasePointerCapture(pointer);
      pointer = null;
    }
    const previous = history.pop();
    if (previous) { lines = previous; save(); }
  }
  undo.addEventListener("click", undoLastChange);
  container.addEventListener("keydown", (event) => {
    if (!(event.ctrlKey || event.metaKey) || event.shiftKey || event.altKey || event.key.toLowerCase() !== "z") return;
    const target = event.target;
    // Preserve native undo while editing the brush character or another field.
    if (target instanceof HTMLElement && (target.isContentEditable ||
      (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) && !target.readOnly)) return;
    event.preventDefault();
    undoLastChange();
  });
  container.querySelector("#editor-reset")!.addEventListener("click", () => {
    remember();
    lines = getAsciiLines(select.value);
    save();
  });
  async function copy(code: boolean): Promise<void> {
    const text = code
      ? JSON.stringify(lines, null, 2)
      : lines.map((line) => `${JSON.stringify(line)},`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      status.textContent = code ? "Array de linhas copiado." : "Linhas entre aspas copiadas, prontas para colar.";
    } catch {
      output.value = text;
      output.focus();
      output.select();
      status.textContent = "Selecionei o texto. Use Ctrl+C para copiar.";
    }
  }
  container.querySelector("#editor-copy")!.addEventListener("click", () => { void copy(false); });
  container.querySelector("#editor-copy-code")!.addEventListener("click", () => { void copy(true); });
  load();
  return drawings;
}
