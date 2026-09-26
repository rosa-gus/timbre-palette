export type ProfileAssemblyMode = "browser" | "server";

interface RuntimeConfigFile {
  profileAnalysisMode?: unknown;
  apiBaseUrl?: unknown;
  serverApiBaseUrl?: unknown;
}

const buildApiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8787"
).replace(/\/$/, "");
const buildServerApiBaseUrl = (
  import.meta.env.VITE_PROFILE_SERVER_API_BASE_URL || buildApiBaseUrl
).replace(/\/$/, "");
const devMode = import.meta.env.DEV
  ? import.meta.env.VITE_PROFILE_ANALYSIS_MODE
  : undefined;

let config = {
  profileAnalysisMode: devMode === "server" ? "server" as const : "browser" as const,
  apiBaseUrl: buildApiBaseUrl,
  serverApiBaseUrl: buildServerApiBaseUrl,
};
let loadPromise: Promise<void> | null = null;

export function loadRuntimeConfig(): Promise<void> {
  if (loadPromise) return loadPromise;
  loadPromise = (async () => {
    try {
      const base = new URL(import.meta.env.BASE_URL, window.location.href);
      const response = await fetch(new URL("profile-analysis-config.json", base), {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;
      const value: unknown = await response.json();
      if (!isObject(value)) return;
      const file = value as RuntimeConfigFile;
      if (file.profileAnalysisMode === "browser" || file.profileAnalysisMode === "server") {
        config.profileAnalysisMode = devMode === "browser" || devMode === "server"
          ? devMode
          : file.profileAnalysisMode;
      }
      if (typeof file.apiBaseUrl === "string" && file.apiBaseUrl.trim()) {
        config.apiBaseUrl = trimSlash(file.apiBaseUrl.trim());
      }
      if (typeof file.serverApiBaseUrl === "string" && file.serverApiBaseUrl.trim()) {
        config.serverApiBaseUrl = trimSlash(file.serverApiBaseUrl.trim());
      }
    } catch {
      // The compiled defaults keep the application available if static config is absent.
    }
  })();
  return loadPromise;
}

export function profileAnalysisMode(): ProfileAssemblyMode {
  return config.profileAnalysisMode;
}

export function apiBaseUrl(): string {
  return config.apiBaseUrl;
}

export function analysisApiBaseUrl(): string {
  return config.profileAnalysisMode === "server"
    ? config.serverApiBaseUrl
    : config.apiBaseUrl;
}

function trimSlash(value: string): string { return value.replace(/\/$/, ""); }
function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
