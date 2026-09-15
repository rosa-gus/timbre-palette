const STORAGE_PREFIX = "app";
export const STORAGE_VERSION = "v1";

function validatePart(value: string, name: string): string {
  if (!value || value.includes(":")) {
    throw new Error(`Invalid storage ${name}: ${value}`);
  }
  return value;
}

export function storageKey(
  identifier: string,
  sector: string,
  version: string = STORAGE_VERSION,
): string {
  return [
    STORAGE_PREFIX,
    validatePart(version, "version"),
    validatePart(identifier, "identifier"),
    validatePart(sector, "sector"),
  ].join(":");
}

export function isStorageAvailable(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage !== null;
  } catch {
    return false;
  }
}

export function getStorageItem<T>(key: string): T | null {
  if (typeof window === "undefined") return null;
  try {
    const value = window.localStorage.getItem(key);
    if (value === null) return null;
    try {
      return JSON.parse(value) as T;
    } catch {
      // Support string values written before this helper serialized JSON.
      return value as T;
    }
  } catch {
    return null;
  }
}

export function setStorageItem<T>(key: string, value: T): boolean {
  if (typeof window === "undefined") return false;
  try {
    const serialized = typeof value === "string" ? value : JSON.stringify(value);
    if (serialized === undefined) return false;
    window.localStorage.setItem(key, serialized);
    return true;
  } catch {
    return false;
  }
}

export function removeStorageItem(key: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    window.localStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}
