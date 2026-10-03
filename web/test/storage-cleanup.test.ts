import { afterEach, expect, it, vi } from "vitest";
import { cleanupStorageVersions } from "../src/utils/storage-cleanup";
import { STORAGE_KEYS } from "../src/utils/storage-keys";

afterEach(() => vi.unstubAllGlobals());

it("removes obsolete registered keys in both stores while preserving current, future and unrelated data", () => {
  const stores = [new Map<string, string>(), new Map<string, string>()];
  const wrap = (items: Map<string, string>) => ({
    get length() { return items.size; },
    key: (index: number) => [...items.keys()][index] ?? null,
    removeItem: (key: string) => items.delete(key),
  });
  vi.stubGlobal("window", { localStorage: wrap(stores[0]), sessionStorage: wrap(stores[1]) });
  const preserved = [STORAGE_KEYS.catalogLastSeen, STORAGE_KEYS.theme, "app:v3:catalog:last-seen",
    "app:v1:unknown:resource", "another-app:v1:catalog:last-seen"];
  for (const store of stores) for (const key of ["app:v1:catalog:last-seen", ...preserved]) store.set(key, "data");
  cleanupStorageVersions();
  cleanupStorageVersions(); // Safe on every startup.
  for (const store of stores) expect([...store.keys()]).toEqual(preserved);
});

it("continues cleaning sessionStorage when localStorage access is blocked", () => {
  const removeItem = vi.fn();
  vi.stubGlobal("window", {
    get localStorage() { throw new Error("blocked"); },
    sessionStorage: { length: 1, key: () => "app:v1:catalog:last-seen", removeItem },
  });
  expect(() => cleanupStorageVersions()).not.toThrow();
  expect(removeItem).toHaveBeenCalledWith("app:v1:catalog:last-seen");
});
