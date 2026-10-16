import { env } from "cloudflare:workers";
import { applyD1Migrations } from "cloudflare:test";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";
import { getInstrument } from "../src/catalog";

beforeAll(async () => { await applyD1Migrations(env.DB, env.TEST_MIGRATIONS!); });
beforeEach(async () => {
  await env.DB.prepare("DELETE FROM editorial_block_translations").run();
  await env.DB.prepare("DELETE FROM editorial_resource_translations").run();
  await env.DB.prepare("DELETE FROM editorial_publications WHERE revision='locale-test'").run();
});

const read = (query = "", slug = "piano") => getInstrument(new URL(`https://api.test/v2/instruments/${slug}${query}`), env, slug);
const base = { name: "Piano", description: "Descrição original.", sound_production: "Produção original.", common_roles: ["harmonia"],
  sections: [], sources: [{ id: "source", title: "Original English title", language: "en" }], further_reading: [], image: null };
async function store(locale: string, content: object, status = "published", source = "source-v1") {
  await env.DB.prepare(`INSERT OR IGNORE INTO editorial_publications (revision, manifest_hash, commit_sha, published_by, status, content_schema_version)
    VALUES ('locale-test', 'hash', 'test', 'test', 'active', 2)`).run();
  await env.DB.prepare(`INSERT INTO editorial_resource_translations
    (resource_type, resource_slug, locale, source_revision, content_revision, status, reviewer, reviewed_at, content_json, publication_revision)
    VALUES ('instrument', 'piano', ?, ?, ?, ?, 'Editor', '2026-10-16', ?, 'locale-test')`)
    .bind(locale, source, `content-${locale}`, status, JSON.stringify(content)).run();
}

describe("editorial content locales", () => {
  it("preserves the default response before the first localized publication", async () => {
    const response = await read();
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Language")).toBe("pt-BR");
    expect(await response.json()).toMatchObject({ slug: "piano", name: "Piano", locale: "pt-BR" });
  });

  it("serves a complete translation and keeps bibliography, image rights and identifiers", async () => {
    const original = await (await read()).json() as { image: Record<string, unknown> | null };
    const imageText = original.image;
    await store("pt-BR", { ...base, image: imageText });
    const translated = { ...base, name: "Piano in English", description: "English description.", sound_production: "English mechanism.",
      common_roles: ["harmony"], image: imageText ? { ...imageText, alt: "Piano keys.", caption: "A piano." } : null };
    await store("en", translated);
    const response = await read("?locale=en");
    expect(response.headers.get("Content-Language")).toBe("en");
    expect(response.headers.get("ETag")).toContain("content-en");
    expect(await response.json()).toMatchObject({ ...translated, slug: "piano", locale: "en", requested_locale: "en", editorial_revision: "locale-test" });
  });

  it.each(["draft", "stale", "deprecated"])("falls back as a whole when translation is %s", async (status) => {
    await store("pt-BR", base);
    await store("en", { ...base, name: "Unavailable English name" }, status);
    const response = await read("?locale=en");
    expect(response.headers.get("Content-Language")).toBe("pt-BR");
    expect(await response.json()).toMatchObject({ name: "Piano", description: base.description, locale: "pt-BR", requested_locale: "en" });
  });

  it("checks source revision and image identity even for approved translations", async () => {
    await store("pt-BR", base);
    await store("en", { ...base, name: "Old translation" }, "published", "old-source");
    expect(await (await read("?locale=en")).json()).toMatchObject({ name: "Piano", locale: "pt-BR" });
    await env.DB.prepare("UPDATE editorial_resource_translations SET source_revision='source-v1' WHERE locale='en'").run();
    // The piano image is present in the image catalog; untranslated captions prevent partial publication.
    expect(await (await read("?locale=en")).json()).toMatchObject({ name: "Piano", locale: "pt-BR" });
  });

  it("canonicalizes requested locales and distinguishes their cache metadata", async () => {
    await store("pt-BR", base);
    const response = await read("?locale=EN-us");
    expect(await response.json()).toMatchObject({ locale: "pt-BR", requested_locale: "en-US" });
    expect(response.headers.get("ETag")).toContain("en-US");
    expect(response.headers.get("ETag")).not.toBe((await read()).headers.get("ETag"));
  });

  it.each(["?locale=", "?locale=en_US", "?locale=en&locale=es"])("rejects malformed locale input: %s", async (query) => {
    const response = await read(query);
    expect(response.status).toBe(422);
    expect(await response.json()).toMatchObject({ error: "invalid_locale" });
  });

  it("withholds a withdrawn source when no publishable version remains", async () => {
    await store("pt-BR", base, "draft");
    await store("en", { ...base, name: "Old translation" }, "stale");
    expect((await read("?locale=en")).status).toBe(404);
  });

  it("does not expose a staging publication or fall through to compatibility text after removal", async () => {
    await store("pt-BR", base);
    await env.DB.prepare(`INSERT INTO editorial_publications (revision, manifest_hash, commit_sha, published_by, status, content_schema_version)
      VALUES ('pending', 'new-hash', 'test', 'test', 'staging', 2)`).run();
    await env.DB.prepare(`INSERT INTO editorial_resource_translations
      SELECT resource_type, resource_slug, locale, source_revision, content_revision, status, reviewer, reviewed_at,
        json_set(content_json, '$.name', 'Unpublished name'), 'pending'
      FROM editorial_resource_translations WHERE publication_revision='locale-test'`).run();
    expect(await (await read()).json()).toMatchObject({ name: "Piano", editorial_revision: "locale-test" });
    await env.DB.prepare("DELETE FROM editorial_resource_translations WHERE publication_revision='locale-test'").run();
    expect((await read()).status).toBe(404);
    await env.DB.prepare("DELETE FROM editorial_resource_translations WHERE publication_revision='pending'").run();
    await env.DB.prepare("DELETE FROM editorial_publications WHERE revision='pending'").run();
  });
});
