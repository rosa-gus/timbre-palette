import { mkdtempSync, readFileSync, writeFileSync, unlinkSync, rmdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it } from "vitest";
import { messageCoverage, renderCoverageTable, updateCoverage } from "../../scripts/generate_locale_types.mjs";

it("counts own messages without counting missing keys, blank text or fallback", () => {
  const base = { message: { first: "First", second: "Second", third: "Third" } };
  expect(messageCoverage(base, { message: { first: "Primeiro", second: " " } })).toEqual({ translated: 1, total: 3 });
  expect(messageCoverage(base, undefined)).toEqual({ translated: 0, total: 3 });
});

it("separates each app and editorial coverage, including content-only locales", () => {
  const base = { one: "One", two: "Two", three: "Three" };
  const table = renderCoverageTable({
    web: { "en-US": base, "pt-BR": { one: "Um" } },
    editorial: { "en-US": { one: "One" } },
  }, { "en-US": { translated: 9999, total: 10000 }, fr: { translated: 0, total: 0 } });
  expect(table).toContain("| en-US | 100% (3/3) | 100% (1/1) | 99.9% (9999/10000) |");
  expect(table).toContain("| pt-BR | 33.3% (1/3) | — | — |");
  expect(table).toContain("| fr | — | — | — (0/0) |");
});

it("rejects stale coverage in check mode and updates only the generated section", async () => {
  const directory = mkdtempSync(join(tmpdir(), "timbre-coverage-"));
  const file = join(directory, "policy.md");
  const before = "# Policy\n\n<!-- translation-coverage:start -->\n\nOld table\n\n<!-- translation-coverage:end -->\n\nKeep these rules.\n";
  writeFileSync(file, before);
  try {
    await expect(updateCoverage(file, "New table", true)).rejects.toThrow("yarn locales:generate");
    expect(readFileSync(file, "utf8")).toBe(before);
    await updateCoverage(file, "New table", false);
    expect(readFileSync(file, "utf8")).toBe(before.replace("Old table", "New table"));
    await expect(updateCoverage(file, "New table", true)).resolves.toBeUndefined();
  } finally {
    unlinkSync(file);
    rmdirSync(directory);
  }
});

it("refuses to replace prose when coverage markers are absent, duplicated or reversed", async () => {
  const directory = mkdtempSync(join(tmpdir(), "timbre-coverage-markers-"));
  const file = join(directory, "policy.md");
  const start = "<!-- translation-coverage:start -->", end = "<!-- translation-coverage:end -->";
  try {
    for (const source of ["# Policy", `${start}${start}${end}`, `${end}${start}`]) {
      writeFileSync(file, source);
      await expect(updateCoverage(file, "Table", false)).rejects.toThrow("coverage markers");
      expect(readFileSync(file, "utf8")).toBe(source);
    }
  } finally {
    unlinkSync(file);
    rmdirSync(directory);
  }
});
