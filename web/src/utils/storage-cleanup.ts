import { STORAGE_KEYS } from "./storage-keys";

/** Remove older versions of registered resources; preserve unrelated and future keys. */
export function cleanupStorageVersions(): void {
  if (typeof window === "undefined") return;
  const versions = new Map(Object.values(STORAGE_KEYS).map((key) => {
    const [prefix, version, identifier, sector] = key.split(":");
    return [`${prefix}:${identifier}:${sector}`, Number(version.slice(1))] as const;
  }));
  for (const name of ["localStorage", "sessionStorage"] as const) {
    try {
      const storage = window[name];
      // Iterate backwards because removing an item shifts the remaining indexes.
      for (let index = storage.length - 1; index >= 0; index--) {
        const key = storage.key(index);
        const parts = key?.match(/^(app):v([1-9]\d*):([^:]+):([^:]+)$/);
        if (!key || !parts) continue;
        const currentVersion = versions.get(`${parts[1]}:${parts[3]}:${parts[4]}`);
        if (currentVersion !== undefined && Number(parts[2]) < currentVersion) storage.removeItem(key);
      }
    } catch { /* Unavailable storage must not block application startup. */ }
  }
}
