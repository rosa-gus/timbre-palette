import { mkdtempSync, writeFileSync, unlinkSync, rmdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { expect, it } from "vitest";
import { flattenCatalog, mergeCatalogs, renderMessageTypes, validateTranslation } from "../../scripts/generate_locale_types.mjs";

it("generates deterministic parameter contracts without duplicating translations", () => {
  const generated = renderMessageTypes('{"plain":"Olá", "greeting":"Olá {name}, {name}! {count}"}');
  expect(generated).toBe(renderMessageTypes('{"greeting":"Other wording: {count} {name}","plain":"Different text"}'));
  expect(generated).toContain('"greeting": "count" | "name";');
  expect(generated).toContain('"plain": never;');
  expect(generated).not.toContain("Olá");
});

it.each([
  '{"duplicate":"first", "duplicate":"second"}',
  '{"nested":{"text":"first", "text":"second"}}',
  '{"empty":{}}',
  '{"dotted.key":"Use nesting"}',
  '{"array":["value"]}',
  '{"count":1}',
  '{"message":"Broken {name"}',
  '{"message":"Broken {invalid name}"}',
  '{"message":"<upper>Unclosed"}',
  '{"message":"<upper>Wrong close</value>"}',
  '{"message":"<upper><value>Nested</value></upper>"}',
  '{"message":"<script>Unknown</script>"}',
  '["not a dictionary"]',
  '{"message":"Not strict JSON",}',
])("rejects invalid catalogs: %s", (source) => {
  expect(() => renderMessageTypes(source)).toThrow();
});

it("preserves parameter contracts inside uppercase markers and allows adjacent wrappers", () => {
  expect(renderMessageTypes('{"message":"<upper>Olá {name}</upper> <value>{count}</value>"}'))
    .toBe(renderMessageTypes('{"message":"Olá {name} {count}"}'));
});

it("preserves full message paths when merging nested domain files", () => {
  const files = [
    { filename: "entry.json", source: '{"entry":{"profileLabel":"Seu perfil"}}' },
    { filename: "analysis.json", source: '{"loading":{"tracksProgress":"Faixas ({current}/{total})"}}' },
  ];
  const catalog = mergeCatalogs(files);
  expect({ ...flattenCatalog(catalog) }).toEqual({
    "entry.profileLabel": "Seu perfil",
    "loading.tracksProgress": "Faixas ({current}/{total})",
  });
  expect(renderMessageTypes(JSON.stringify(catalog))).toContain('"loading.tracksProgress": "current" | "total";');
});

it("rejects namespace conflicts instead of silently overwriting another file", () => {
  expect(() => mergeCatalogs([
    { filename: "first.json", source: '{"entry":{"title":"Title"}}' },
    { filename: "second.json", source: '{"entry":{"description":"Description"}}' },
  ])).toThrow("conflicting namespace entry");
});

it("retains compile-time validation of JSON message keys and named parameters", () => {
  const directory = mkdtempSync(join(tmpdir(), "timbre-locale-types-"));
  const filename = join(directory, "contract.ts");
  const web = fileURLToPath(new URL("../src/i18n/runtime", import.meta.url));
  const editorial = fileURLToPath(new URL("../../editorial/src/i18n/runtime", import.meta.url));
  writeFileSync(filename, `
    import { t } from ${JSON.stringify(web)};
    import { t as editorialText } from ${JSON.stringify(editorial)};
    t("loading.tracksProgress", { current: 1, total: 4 });
    t("entry.profileLabel");
    editorialText("validation.requiredText", { label: "Piano" });
    // @ts-expect-error Missing named parameter.
    t("loading.tracksProgress", { current: 1 });
    // @ts-expect-error Unknown message key.
    t("unknown.message");
    // @ts-expect-error No parameters for a plain message.
    t("entry.profileLabel", { name: "value" });
    // @ts-expect-error Wrong parameter name.
    editorialText("validation.requiredText", { name: "Piano" });
    // @ts-expect-error Catalog ownership remains separate.
    editorialText("entry.profileLabel");
  `);
  try {
    const program = ts.createProgram([filename], {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
      moduleResolution: ts.ModuleResolutionKind.Bundler,
      resolveJsonModule: true,
      strict: true,
      noEmit: true,
      skipLibCheck: true,
      types: [],
    });
    const errors = ts.getPreEmitDiagnostics(program).map((diagnostic) =>
      ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"));
    expect(errors).toEqual([]);
  } finally {
    unlinkSync(filename);
    rmdirSync(directory);
  }
});

it("rejects translation key, parameter and semantic wrapper mismatches", () => {
  const base = { title: "<emphasis>Olá {name}</emphasis>" };
  expect(() => validateTranslation(base, { title: "<emphasis>Hello {name}</emphasis>" })).not.toThrow();
  expect(() => validateTranslation(base, { other: "Hello {name}" })).toThrow();
  expect(() => validateTranslation(base, { title: "<emphasis>Hello {user}</emphasis>" })).toThrow();
  expect(() => validateTranslation(base, { title: "Hello {name}" })).toThrow();
});
