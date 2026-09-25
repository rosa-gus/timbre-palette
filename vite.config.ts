import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { readFileSync } from "node:fs";

function sourceVersion(path: string): string {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const version = source.match(/\bversion(?:\s*:\s*str)?\s*=\s*"([^"]+)"/);
  if (!version) throw new Error(`Version missing in ${path}`);
  return version[1];
}

const product = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf8"),
) as { version: string; productStatus: string };

const productStatuses = [
  "prototype",
  "development",
  "beta",
  "pilot",
  "stable",
] as const;
if (!productStatuses.some((status) => status === product.productStatus)) {
  throw new Error(
    `Invalid productStatus in package.json: ${product.productStatus}. Expected one of: ${productStatuses.join(", ")}`,
  );
}

export default defineConfig({
  define: {
    __PRODUCT_METADATA__: JSON.stringify({
      product: product.version,
      status: product.productStatus,
      method: sourceVersion("./src/palette_api/methodology.py"),
      api: sourceVersion("./src/palette_api/api.py"),
    }),
  },
  plugins: [svelte({ configFile: "../svelte.config.js" })],
  root: "web",
  publicDir: "../public",
  base: "./",
  server: { port: 5173, strictPort: true },
  optimizeDeps: {
    exclude: ["bits-ui"],
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
