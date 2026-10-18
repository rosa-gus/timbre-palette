import { describe, it, expect } from "vitest";
import { execFileSync } from "node:child_process";
import { initialSnapshot, sourceSheets, sourceRevision, legacySourceRevision, snapshotFromSheets } from "../../editorial/src/content";

describe("editorial content snapshots", () => {
  it("round-trips neutral entities, source metadata and localized text", () => {
    const sheets = sourceSheets(initialSnapshot);
    expect(sourceSheets(snapshotFromSheets(sheets, {}))).toEqual(sheets);
    expect(sheets).toHaveLength(23);
    expect(initialSnapshot.entities[0]).not.toHaveProperty("name");
    expect(initialSnapshot.locales["pt-BR"][0]).not.toHaveProperty("sources");
  });

  it("uses the same source revision in the editor and publisher", async () => {
    const sheet = sourceSheets(initialSnapshot)[0];
    const published = execFileSync("python3", ["-c", `from pathlib import Path
from scripts.publish_editorial import load_manifest
from scripts.editorial_content import source_revision, legacy_source_revision
import json
sheet = load_manifest(Path('editorial/content/catalog.json'))[0]
print(json.dumps([source_revision(sheet), legacy_source_revision(sheet)]))`], { encoding: "utf8" }).trim();
    const [current, legacy] = JSON.parse(published) as [string, string];
    expect(await sourceRevision(sheet)).toBe(current);
    expect(await legacySourceRevision(sheet)).toBe(legacy);
    const changed = structuredClone(sheet);
    changed.resource.sections[0].text += " Updated.";
    expect(await sourceRevision(changed)).not.toBe(current);
  });
});


it("preserves withdrawal across editor exports even when the old review remains approved", () => {
  const snapshot = structuredClone(initialSnapshot);
  snapshot.locales["pt-BR"][0].status = "deprecated";
  expect(snapshot.locales["pt-BR"][0].review.claim_support_verified).toBe(true);
  const exported = snapshotFromSheets(sourceSheets(snapshot), snapshot.locales);
  expect(exported.locales["pt-BR"][0].status).toBe("deprecated");
  expect(snapshotFromSheets(sourceSheets(exported), exported.locales).locales["pt-BR"][0].status).toBe("deprecated");
});


it("ignores operational metadata but preserves content and publication sensitivity without mutating the sheet", async () => {
  const source = structuredClone(sourceSheets(initialSnapshot)[0]);
  const before = JSON.stringify(source);
  const revision = await sourceRevision(source);
  const operational = structuredClone(source);
  operational.resource.catalog_version = "new-version";
  operational.resource.image_catalog_version = "new-images";
  operational.resource.tone!.highlight = "#ffffff";
  operational.resource.image!.variants[0].url += "?updated=1";
  operational.resource.image!.credit.photographer = "Updated attribution";
  operational.review.editorial_note = "Operational note";
  operational.review.reviewed_at = "2026-10-17";
  operational.resource.sections[0].review.reviewer = "New reviewer";
  operational.resource.sources[0].accessed_at = "2026-10-17";
  expect(await sourceRevision(operational)).toBe(revision);
  expect(await legacySourceRevision(operational)).not.toBe(await legacySourceRevision(source));
  for (const change of [
    (sheet: typeof source) => { sheet.resource.description += " Updated."; },
    (sheet: typeof source) => { sheet.resource.image!.asset_id = "new-image"; },
    (sheet: typeof source) => { sheet.resource.image!.alt += " Updated."; },
    (sheet: typeof source) => { sheet.resource.sections[0].status = "deprecated"; },
    (sheet: typeof source) => { sheet.resource.sections[0].citations[0].note = "Changed evidence"; },
    (sheet: typeof source) => { sheet.resource.sources[0].metadata_verified = false; },
  ]) {
    const changed = structuredClone(source);
    change(changed);
    expect(await sourceRevision(changed)).not.toBe(revision);
  }
  expect(JSON.stringify(source)).toBe(before);
});
