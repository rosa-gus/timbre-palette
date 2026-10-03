import { describe, expect, it, vi } from "vitest";
import worker from "../src/index";

describe("API documentation", () => {
  it.each(["/docs", "/docs/"])("serves the UI at %s without bindings or upstream requests", async (path) => {
    const upstream = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Unexpected external request"));
    try {
      const response = await worker.fetch(new Request(`https://api.test${path}`), {} as Env);
      expect(response.status).toBe(200);
      expect(response.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
      const html = await response.text();
      expect(html).toContain("SwaggerUIBundle({");
      expect(html).toContain('url: "/openapi.json"');
      expect(html).toContain("validatorUrl: null");
      expect(upstream).not.toHaveBeenCalled();
    } finally { upstream.mockRestore(); }
  });

  it("serves the UI's OpenAPI document without database or protection bindings", async () => {
    const response = await worker.fetch(new Request("https://api.test/openapi.json"), {} as Env);
    expect(response.status).toBe(200);
    const document = await response.json() as { openapi: string; paths: Record<string, unknown> };
    expect(document.openapi).toBe("3.1.0");
    expect(document.paths).toHaveProperty("/v3/evidence");
  });

  it("rejects unsupported methods instead of rendering documentation", async () => {
    const response = await worker.fetch(new Request("https://api.test/docs", { method: "POST" }), {} as Env);
    expect(response.status).toBe(405);
  });
});
