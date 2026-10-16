import { describe, it, expect } from "vitest";
import { execFileSync } from "node:child_process";
import { initialSnapshot, sourceSheets, sourceRevision, snapshotFromSheets } from "../../editorial/src/content";

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
from scripts.editorial_content import source_revision
print(source_revision(load_manifest(Path('editorial/content/catalog.json'))[0]))`], { encoding: "utf8" }).trim();
    expect(await sourceRevision(sheet)).toBe(published);
    const changed = structuredClone(sheet);
    changed.resource.sections[0].text += " Updated.";
    expect(await sourceRevision(changed)).not.toBe(published);
  });
});
