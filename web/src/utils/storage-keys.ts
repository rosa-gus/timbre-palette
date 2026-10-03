import { storageKey } from "../storage";

// Format: app:<version>:<identifier>:<sector>, e.g. app:v1:ui:theme.
// Add every browser storage key here. Use the identifier for the feature and
// the sector for the stored resource; bump its version when semantics change.
export const STORAGE_KEYS = {
  theme: storageKey("ui", "theme"),
  asciiEditor: storageKey("sharing", "ascii-editor"),
  // v2 counts the active snapshot projection, unlike the former catalog stats.
  catalogLastSeen: storageKey("catalog", "last-seen", "v2"),
  editorialInstruments: storageKey("editorial", "instruments"),
  historyProgress: storageKey("analysis", "history-progress"),
} as const;
