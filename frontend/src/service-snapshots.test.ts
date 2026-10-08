import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ServiceSnapshots, serviceSnapshots } from "./service-snapshots";
import { setCsrf } from "./api";

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
};
let store: ServiceSnapshots;
let documentFixture: EventTarget & { hidden: boolean };
beforeEach(() => {
  vi.useFakeTimers();
  store = new ServiceSnapshots();
  documentFixture = Object.assign(new EventTarget(), { hidden: false });
  vi.stubGlobal("document", documentFixture);
});
afterEach(() => {
  store.clear();
  serviceSnapshots.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("session service snapshots", () => {
  it("publishes the fast card immediately, independent of a two-second slow service", async () => {
    const slow = deferred<string>();
    const observed: number[] = [];
    const baseline: number[] = [];
    const start = Date.now();
    const fast = Promise.resolve("Plex");
    void Promise.all([slow.promise, fast]).then(() =>
      baseline.push(Date.now() - start),
    );
    store.subscribe(() => {
      if (store.get("runtime:plex").data && !observed.length)
        observed.push(Date.now() - start);
    });
    store.acquire("runtime:seedbox", 10000, () => slow.promise);
    store.acquire("runtime:plex", 10000, () => fast);
    await vi.advanceTimersByTimeAsync(0);
    expect(observed).toEqual([0]);
    expect(store.get("runtime:seedbox").data).toBeUndefined();
    await vi.advanceTimersByTimeAsync(2000);
    slow.resolve("Seedbox");
    await vi.advanceTimersByTimeAsync(0);
    expect(store.get("runtime:seedbox").data).toBe("Seedbox");
    expect(baseline).toEqual([2000]);
    expect(observed).toEqual([0]);
  });
  it("keeps last good data explicitly stale after a partial error", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce("last good")
      .mockRejectedValueOnce(new Error("offline"));
    store.acquire("runtime:plex", 10000, load);
    store.acquire("runtime:cloudflare", 10000, async () => "online");
    await vi.advanceTimersByTimeAsync(10000);
    expect(store.get("runtime:plex")).toMatchObject({
      data: "last good",
      stale: true,
      error: "offline",
    });
    expect(store.get("runtime:cloudflare")).toMatchObject({
      data: "online",
      stale: false,
    });
  });
  it("reuses fresh posters on navigation and marks expired posters stale while refreshing", async () => {
    const pending = deferred<string>();
    const load = vi
      .fn()
      .mockResolvedValueOnce("covers")
      .mockImplementationOnce(() => pending.promise);
    let release = store.acquire("recent:plex", 60000, load);
    await vi.advanceTimersByTimeAsync(0);
    release();
    release = store.acquire("recent:plex", 60000, load);
    expect(store.get("recent:plex")).toMatchObject({
      data: "covers",
      stale: false,
    });
    expect(load).toHaveBeenCalledTimes(1);
    release();
    await vi.advanceTimersByTimeAsync(60000);
    store.acquire("recent:plex", 60000, load);
    expect(store.get("recent:plex")).toMatchObject({
      data: "covers",
      stale: true,
      refreshing: true,
    });
  });
  it("deduplicates mounted consumers and never overlaps slow polling", async () => {
    const pending = deferred<string>();
    const load = vi.fn(() => pending.promise);
    const first = store.acquire("runtime:plex", 10000, load);
    store.acquire("runtime:plex", 10000, load);
    first();
    await vi.advanceTimersByTimeAsync(30000);
    expect(load).toHaveBeenCalledTimes(1);
    pending.resolve("done");
    await vi.advanceTimersByTimeAsync(10000);
    expect(load).toHaveBeenCalledTimes(2);
  });
  it("pauses hidden polling and refreshes on visibility return without overlap", async () => {
    const load = vi.fn(async () => "value");
    store.acquire("runtime:plex", 10000, load);
    await vi.advanceTimersByTimeAsync(0);
    documentFixture.hidden = true;
    await vi.advanceTimersByTimeAsync(20000);
    expect(load).toHaveBeenCalledTimes(1);
    documentFixture.hidden = false;
    documentFixture.dispatchEvent(new Event("visibilitychange"));
    documentFixture.dispatchEvent(new Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0);
    expect(load).toHaveBeenCalledTimes(2);
  });
  it("aborts unmounted and deleted app requests and ignores their late results", async () => {
    const old = deferred<string>();
    let signal!: AbortSignal;
    const release = store.acquire("runtime:old", 10000, (value) => {
      signal = value;
      return old.promise;
    });
    release();
    expect(signal.aborted).toBe(true);
    store.prune(["new"]);
    store.acquire("runtime:new", 10000, async () => "new data");
    old.resolve("private old data");
    await vi.advanceTimersByTimeAsync(0);
    expect(store.get("runtime:old").data).toBeUndefined();
    expect(store.get("runtime:new").data).toBe("new data");
  });
  it("clears both data types on credential transitions, including same-account login", async () => {
    const old = deferred<string>();
    let signal!: AbortSignal;
    serviceSnapshots.acquire(
      "runtime:plex",
      10000,
      async () => "private runtime",
    );
    serviceSnapshots.acquire("recent:plex", 60000, (value) => {
      signal = value;
      return old.promise;
    });
    await vi.advanceTimersByTimeAsync(0);
    setCsrf("account-a");
    expect(signal.aborted).toBe(true);
    old.resolve("private covers");
    await vi.advanceTimersByTimeAsync(0);
    expect(serviceSnapshots.get("runtime:plex").data).toBeUndefined();
    expect(serviceSnapshots.get("recent:plex").data).toBeUndefined();
    serviceSnapshots.acquire("recent:plex", 60000, async () => "account a");
    await vi.advanceTimersByTimeAsync(0);
    setCsrf("");
    setCsrf("account-b");
    expect(serviceSnapshots.get("recent:plex").data).toBeUndefined();
  });
  it("fences an aborted old response when the same app is mounted again", async () => {
    const old = deferred<string>();
    const load = vi
      .fn()
      .mockImplementationOnce(() => old.promise)
      .mockResolvedValueOnce("fresh");
    const release = store.acquire("runtime:plex", 10000, load);
    release();
    store.acquire("runtime:plex", 10000, load);
    await vi.advanceTimersByTimeAsync(0);
    old.resolve("obsolete");
    await vi.advanceTimersByTimeAsync(0);
    expect(store.get("runtime:plex")).toMatchObject({
      data: "fresh",
      stale: false,
    });
  });
  it("ages a retained observation while hidden without calling the API", async () => {
    const load = vi.fn(async () => "retained");
    store.acquire("runtime:plex", 10000, load);
    await vi.advanceTimersByTimeAsync(0);
    documentFixture.hidden = true;
    await vi.advanceTimersByTimeAsync(10000);
    expect(store.get("runtime:plex")).toMatchObject({
      data: "retained",
      stale: true,
    });
    expect(load).toHaveBeenCalledTimes(1);
  });
  it("bounds retained inactive observations and removes deleted app data", async () => {
    for (let i = 0; i < 70; i++) {
      const release = store.acquire(`recent:${i}`, 60000, async () => i);
      await vi.advanceTimersByTimeAsync(0);
      release();
    }
    expect(store.get("recent:0").data).toBeUndefined();
    expect(store.get("recent:69").data).toBe(69);
    store.prune([]);
    expect(store.get("recent:69").data).toBeUndefined();
  });
});
