import { afterEach, expect, it, vi } from "vitest";
import { getInstrument } from "../src/api/client";
import { localizedInstrument } from "../src/i18n/resources";
import type { InstrumentResource } from "../src/api/types";

vi.mock("../src/api/client", () => ({ getInstrument: vi.fn() }));
const lookup = vi.mocked(getInstrument);
const resource = (name: string) => ({ name, locale: "en-US" }) as InstrumentResource;
function deferred() {
  let resolve!: (value: InstrumentResource) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<InstrumentResource>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
afterEach(() => { lookup.mockReset(); vi.useRealTimers(); });

it("shares a pending request and caches its successful result", async () => {
  const request = deferred(); lookup.mockReturnValue(request.promise);
  const first = localizedInstrument("dedup-shared", new AbortController().signal, "en-US");
  const second = localizedInstrument("dedup-shared", new AbortController().signal, "en-US");
  await Promise.resolve();
  expect(lookup).toHaveBeenCalledTimes(1);
  const translated = resource("Shared"); request.resolve(translated);
  expect(await first).toBe(translated);
  expect(await second).toBe(translated);
  expect(await localizedInstrument("dedup-shared", new AbortController().signal, "en-US")).toBe(translated);
  expect(lookup).toHaveBeenCalledTimes(1);
});

it("cancels one consumer without aborting the other consumer's request", async () => {
  const request = deferred(); lookup.mockReturnValue(request.promise);
  const controller = new AbortController();
  const first = localizedInstrument("dedup-independent", controller.signal, "en-US");
  const cancelled = expect(first).rejects.toMatchObject({ name: "AbortError" });
  const second = localizedInstrument("dedup-independent", new AbortController().signal, "en-US");
  await Promise.resolve(); controller.abort(); await cancelled;
  expect(lookup.mock.calls[0][1].aborted).toBe(false);
  request.resolve(resource("Still available"));
  expect((await second).name).toBe("Still available");
  expect(lookup).toHaveBeenCalledTimes(1);
});

it("aborts after the last consumer leaves and ignores an abandoned late response", async () => {
  const abandoned = deferred(), fresh = deferred();
  lookup.mockReturnValueOnce(abandoned.promise).mockReturnValueOnce(fresh.promise);
  const one = new AbortController(), two = new AbortController();
  const first = localizedInstrument("dedup-abandoned", one.signal, "en-US");
  const second = localizedInstrument("dedup-abandoned", two.signal, "en-US");
  const stopped = Promise.allSettled([first, second]);
  await Promise.resolve(); one.abort();
  expect(lookup.mock.calls[0][1].aborted).toBe(false);
  two.abort(); await stopped;
  expect(lookup.mock.calls[0][1].aborted).toBe(true);
  const next = localizedInstrument("dedup-abandoned", new AbortController().signal, "en-US");
  await Promise.resolve(); expect(lookup).toHaveBeenCalledTimes(2);
  abandoned.resolve(resource("Abandoned"));
  await Promise.resolve(); await Promise.resolve();
  const follower = localizedInstrument("dedup-abandoned", new AbortController().signal, "en-US");
  fresh.resolve(resource("Fresh"));
  expect((await next).name).toBe("Fresh");
  expect((await follower).name).toBe("Fresh");
  expect((await localizedInstrument("dedup-abandoned", new AbortController().signal, "en-US")).name).toBe("Fresh");
  expect(lookup).toHaveBeenCalledTimes(2);
});

it("separates locale and slug identities", async () => {
  lookup.mockImplementation(async (slug, _signal, language) => resource(`${language}:${slug}`));
  const requests = [
    localizedInstrument("dedup-locale", new AbortController().signal, "en-US"),
    localizedInstrument("dedup-locale", new AbortController().signal, "pt-BR"),
    localizedInstrument("dedup-other", new AbortController().signal, "en-US"),
  ];
  expect((await Promise.all(requests)).map(({ name }) => name)).toEqual(["en-US:dedup-locale", "pt-BR:dedup-locale", "en-US:dedup-other"]);
  expect(lookup).toHaveBeenCalledTimes(3);
});

it("does not cache failures and allows a subsequent retry", async () => {
  const request = deferred(); lookup.mockReturnValueOnce(request.promise);
  const first = localizedInstrument("dedup-failure", new AbortController().signal, "en-US");
  const second = localizedInstrument("dedup-failure", new AbortController().signal, "en-US");
  const failed = Promise.allSettled([first, second]);
  await Promise.resolve(); request.reject(new Error("Unavailable"));
  expect((await failed).every(({ status }) => status === "rejected")).toBe(true);
  lookup.mockResolvedValue(resource("Recovered"));
  expect((await localizedInstrument("dedup-failure", new AbortController().signal, "en-US")).name).toBe("Recovered");
  expect(lookup).toHaveBeenCalledTimes(2);
});

it("rejects aborted consumers even for cached resources", async () => {
  lookup.mockResolvedValue(resource("Cached"));
  await localizedInstrument("dedup-cached-abort", new AbortController().signal, "en-US");
  const controller = new AbortController(); controller.abort();
  await expect(localizedInstrument("dedup-cached-abort", controller.signal, "en-US")).rejects.toMatchObject({ name: "AbortError" });
  expect(lookup).toHaveBeenCalledTimes(1);
});

it("expires completed entries after five minutes", async () => {
  vi.useFakeTimers(); lookup.mockResolvedValue(resource("Old"));
  await localizedInstrument("dedup-expiry", new AbortController().signal, "en-US");
  await vi.advanceTimersByTimeAsync(300_001);
  lookup.mockResolvedValue(resource("Updated"));
  expect((await localizedInstrument("dedup-expiry", new AbortController().signal, "en-US")).name).toBe("Updated");
  expect(lookup).toHaveBeenCalledTimes(2);
});


it("does not start an abandoned request when cancellation precedes its fetch", async () => {
  lookup.mockResolvedValue(resource("Fresh"));
  const controller = new AbortController();
  const cancelled = localizedInstrument("dedup-before-start", controller.signal, "en-US");
  const rejected = expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
  controller.abort();
  const next = localizedInstrument("dedup-before-start", new AbortController().signal, "en-US");
  await rejected;
  expect((await next).name).toBe("Fresh");
  expect(lookup).toHaveBeenCalledTimes(1);
});
