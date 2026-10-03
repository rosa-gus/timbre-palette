import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";
import type { Reporter } from "vitest/reporters";

function setting(name: string, fallback: number, min: number, max: number): number {
  const value = Number(process.env[name] ?? fallback);
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    throw new Error(`${name} must be an integer between ${min} and ${max}.`);
  }
  return value;
}
const options = {
  requests: setting("STRESS_REQUESTS", 250, 100, 5000),
  concurrency: setting("STRESS_CONCURRENCY", 50, 2, 500),
  upstreamMs: setting("STRESS_UPSTREAM_MS", 80, 1, 1000),
};
if (Math.ceil(options.requests / options.concurrency) * options.upstreamMs > 30_000) {
  throw new Error("The simulated upstream workload must fit within 30 seconds. Increase concurrency or reduce requests/delay.");
}
const output = resolve(process.env.STRESS_OUTPUT ?? ".wrangler/stress-api-report.json");
const scenarios: Record<string, unknown>[] = [];
const reporter: Reporter = {
  onTestRunEnd(modules, errors, reason) {
    mkdirSync(dirname(output), { recursive: true });
    writeFileSync(output, JSON.stringify({
      generated_at: new Date().toISOString(), options,
      passed: modules.length > 0 && modules.every((module) => module.state() === "passed") && errors.length === 0 && reason === "passed",
      limitations: "Local handler calls, emulated bindings, synthetic data and mocked Last.fm. Latency includes local scheduling; it does not predict edge capacity.",
      scenarios,
    }, null, 2) + "\n");
    console.table(scenarios.map((row) => ({ scenario: row.scenario, accepted: row.accepted,
      refused: row.refused, unexpected: row.unexpected, p95_ms: row.p95_ms,
      upstream_calls: row.upstream_calls, upstream_peak: row.upstream_peak,
      d1_reads: row.d1_reads, d1_writes: row.d1_writes })));
    console.log(`Stress report: ${output}`);
  },
};

export default defineConfig({
  plugins: [cloudflareTest({
    wrangler: { configPath: "./wrangler.jsonc" },
    miniflare: { bindings: { LASTFM_API_KEY: "local-stress-key", STRESS_OPTIONS: JSON.stringify(options),
      TEST_MIGRATIONS: await readD1Migrations("./migrations") } },
  })],
  test: {
    include: ["workers/api/stress/**/*.test.ts"], fileParallelism: false,
    testTimeout: 60_000, hookTimeout: 60_000, reporters: ["default", reporter],
    onConsoleLog(log) {
      for (const line of log.split("\n")) {
        if (line.startsWith("STRESS_RESULT ")) scenarios.push(JSON.parse(line.slice("STRESS_RESULT ".length)));
      }
      return false;
    },
  },
});
