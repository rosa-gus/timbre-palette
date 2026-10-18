import { afterEach, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const apps = [
  { name: "web", catalog: "../src/i18n/catalog.generated", runtime: () => import("../src/i18n/runtime") },
  { name: "editorial", catalog: "../../editorial/src/i18n/catalog.generated", runtime: () => import("../../editorial/src/i18n/runtime") },
];

afterEach(() => {
  for (const app of apps) vi.doUnmock(app.catalog);
  vi.resetModules();
  vi.unstubAllGlobals();
});

it.each(apps)("keeps the latest selection and its side effects when Portuguese loads late in $name", async (app) => {
  vi.resetModules();
  const catalog = await vi.importActual(app.catalog);
  let release!: () => void;
  let started!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  const loading = new Promise<void>((resolve) => { started = resolve; });
  vi.doMock(app.catalog, async () => { started(); await pending; return catalog; });
  const runtime = await app.runtime();
  const setItem = vi.fn(), replaceState = vi.fn();
  const documentElement = { lang: "", dir: "" };
  vi.stubGlobal("localStorage", { setItem });
  vi.stubGlobal("document", { documentElement });
  vi.stubGlobal("window", { location: { href: "https://palette.test/?profile=listener" }, history: { state: { report: true }, replaceState } });
  const events: string[] = [];
  const unsubscribe = runtime.localeStore.subscribe((value) => events.push(value));
  let settled = false;
  const portuguese = runtime.setLocale("pt-BR").then(() => { settled = true; });
  try {
    await loading;
    await runtime.setLocale("en-US");
    expect(settled).toBe(false);
    expect(runtime.locale).toBe("en-US");
    release();
    await portuguese;
    expect(runtime.locale).toBe("en-US");
    expect(get(runtime.localeStore)).toBe("en-US");
    expect(documentElement.lang).toBe("en-US");
    expect(setItem).toHaveBeenCalledTimes(1);
    expect(setItem).toHaveBeenCalledWith(`app:v1:${app.name}:locale`, "en-US");
    expect(replaceState).toHaveBeenCalledTimes(1);
    expect((replaceState.mock.calls[0][2] as URL).searchParams.get("lang")).toBe("en-US");
    expect(events).not.toContain("pt-BR");
    if (app.name === "web")
      expect((runtime as typeof import("../src/i18n/runtime")).t("entry.profileLabel")).toBe("Your Last.fm profile");
    else
      expect((runtime as typeof import("../../editorial/src/i18n/runtime")).t("sheet.editLabel")).toBe("Edit profile");
  } finally {
    release();
    await portuguese;
    unsubscribe();
  }
});
