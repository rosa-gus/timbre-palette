import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  root: "editorial",
  base: "./",
  plugins: [svelte({ configFile: "../svelte.config.js" })],
  server: { port: 5174, strictPort: true },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
