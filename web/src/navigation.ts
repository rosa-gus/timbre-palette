/**
 * Returns the current application path with one leading and trailing slash.
 *
 * This keeps internal links inside a repository-hosted GitHub Pages site,
 * where the application may live at /timbre-palette/ instead of at /.
 */
export function normalizePathname(pathname?: string): string {
  const source = pathname ?? (
    typeof window === "undefined" ? "/" : window.location.pathname
  );
  const pathOnly = source.split(/[?#]/, 1)[0] || "/";
  const normalized = pathOnly.replace(/\/+/g, "/").replace(/^\/+|\/+$/g, "");
  return normalized ? `/${normalized}/` : "/";
}
