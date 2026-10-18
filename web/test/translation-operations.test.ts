import { expect, it } from "vitest";
import { initialSnapshot, sourceSheets, localizedText } from "../../editorial/src/content";
import { startTranslation, rebaseTranslation } from "../../editorial/src/translation-operations";
import type { Translations } from "../../editorial/src/content";

function pendingRevision() {
  let resolve!: (value: string) => void;
  const promise = new Promise<string>((done) => { resolve = done; });
  return { resolve, revision: () => promise };
}
function context() {
  const sheet = structuredClone(sourceSheets(initialSnapshot)[0]);
  const translation = structuredClone(localizedText(sheet));
  translation.source_revision = "previous";
  translation.sections[0].text = "Translated section";
  const translations: Translations = { "en-US": [translation] };
  return { sheet, locale: "en-US", translations };
}

it("discards pending creation when its editor context is invalidated", async () => {
  const state = context(); state.translations = {};
  const pending = pendingRevision();
  let current = true;
  const work = startTranslation(state, () => current, pending.revision);
  current = false;
  pending.resolve("revision");
  expect(await work).toBe(false);
  expect(state.translations).toEqual({});
});

it("commits only one draft when creation overlaps", async () => {
  const state = context(); state.translations = {};
  const first = pendingRevision(), second = pendingRevision();
  const old = startTranslation(state, () => true, first.revision);
  const recent = startTranslation(state, () => true, second.revision);
  second.resolve("newest"); await recent;
  first.resolve("older"); expect(await old).toBe(false);
  expect(state.translations["en-US"]).toHaveLength(1);
  expect(state.translations["en-US"][0].source_revision).toBe("newest");
});

it("does not commit a draft if its source changes during hashing", async () => {
  const state = context(); state.translations = {};
  const pending = pendingRevision();
  const work = startTranslation(state, () => true, pending.revision);
  state.sheet.resource.description += " Changed.";
  pending.resolve("old-source");
  expect(await work).toBe(false);
  expect(state.translations).toEqual({});
});

it("does not mutate any translation before rebase finishes or after cancellation", async () => {
  const state = context();
  const before = structuredClone(state.translations);
  const pending = pendingRevision();
  let current = true;
  const work = rebaseTranslation(state, () => current, pending.revision);
  expect(state.translations).toEqual(before);
  current = false; pending.resolve("revision");
  expect(await work).toBe(false);
  expect(state.translations).toEqual(before);
});

it.each(["source", "translation", "replacement"])("preserves %s changes made while a rebase is pending", async (change) => {
  const state = context();
  const pending = pendingRevision();
  const work = rebaseTranslation(state, () => true, pending.revision);
  if (change === "source") state.sheet.resource.description += " Changed.";
  if (change === "translation") state.translations["en-US"][0].sections[0].text = "New edit";
  if (change === "replacement") state.translations["en-US"][0] = structuredClone(state.translations["en-US"][0]);
  const edited = structuredClone(state.translations);
  pending.resolve("old-source");
  expect(await work).toBe(false);
  expect(state.translations).toEqual(edited);
});

it("rebases atomically, preserving translated text, resetting review and retaining withdrawal", async () => {
  const state = context();
  const target = state.translations["en-US"][0];
  target.status = "deprecated";
  state.sheet.resource.image = null;
  state.sheet.resource.sections.push({ ...structuredClone(state.sheet.resource.sections[0]), id: "new-section", text: "New source section" });
  expect(await rebaseTranslation(state, () => true, async () => "current-source")).toBe(true);
  expect(state.translations["en-US"][0]).toBe(target);
  expect(target.source_revision).toBe("current-source");
  expect(target.sections.map(({ text }) => text)).toEqual(["Translated section", "New source section"]);
  expect(target.sections.every((block) => block.status === "draft" && !block.review.claim_support_verified)).toBe(true);
  expect(target.image).toBeNull();
  expect(target.status).toBe("deprecated");
  expect(target.review.claim_support_verified).toBe(false);
});
