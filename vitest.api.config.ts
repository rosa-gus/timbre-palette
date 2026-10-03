import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [cloudflareTest({
    wrangler: { configPath: "./wrangler.jsonc" },
    miniflare: {
      bindings: { LASTFM_API_KEY: "test-key", TEST_MIGRATIONS: await readD1Migrations("./migrations") },
    },
  })],
  test: { include: ["workers/api/test/**/*.test.ts"], fileParallelism: false },
});
