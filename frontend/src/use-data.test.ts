import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadData } from "./use-data";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const response = (data: unknown) => Response.json({ data });

describe("page data request lifecycle", () => {
  it("starts one request and publishes its data", async () => {
    const fetch = vi.fn().mockResolvedValue(response(["installed"]));
    vi.stubGlobal("fetch", fetch);
    const onData = vi.fn();
    const onError = vi.fn();
    const cancel = loadData("/apps", onData, onError);
    await vi.runAllTimersAsync();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(onData).toHaveBeenCalledWith(["installed"]);
    expect(onError).not.toHaveBeenCalled();
    cancel();
  });

  it("retains the two bounded retries for temporary failures", async () => {
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new Error("Restarting"))
      .mockRejectedValueOnce(new Error("Restarting"))
      .mockResolvedValueOnce(response(["recovered"]));
    vi.stubGlobal("fetch", fetch);
    const onData = vi.fn();
    const onError = vi.fn();
    const cancel = loadData("/apps", onData, onError);
    await vi.runAllTimersAsync();
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(onData).toHaveBeenCalledWith(["recovered"]);
    expect(onError).not.toHaveBeenCalled();
    cancel();
  });

  it("reports failure only after retry exhaustion", async () => {
    const fetch = vi.fn().mockRejectedValue(new Error("Offline"));
    vi.stubGlobal("fetch", fetch);
    const onData = vi.fn();
    const onError = vi.fn();
    const cancel = loadData("/apps", onData, onError);
    await vi.runAllTimersAsync();
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(onData).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledExactlyOnceWith("Offline");
    cancel();
  });

  it("cancels pending retries when the page unmounts or reloads", async () => {
    const fetch = vi.fn().mockRejectedValue(new Error("Offline"));
    vi.stubGlobal("fetch", fetch);
    const onError = vi.fn();
    const cancel = loadData("/apps", vi.fn(), onError);
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBe(1);
    cancel();
    await vi.runAllTimersAsync();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
    expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
  });

  it("ignores a stale response even when the transport ignores abort", async () => {
    let resolve!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<Response>((done) => {
          resolve = done;
        }),
      ),
    );
    const onData = vi.fn();
    const onError = vi.fn();
    const cancel = loadData("/apps", onData, onError);
    cancel();
    resolve(response(["stale"]));
    await vi.runAllTimersAsync();
    expect(onData).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it("never retries or reports a cancelled in-flight failure", async () => {
    let reject!: (reason: Error) => void;
    const fetch = vi.fn().mockReturnValue(
      new Promise<Response>((_, fail) => {
        reject = fail;
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const onError = vi.fn();
    const cancel = loadData("/apps", vi.fn(), onError);
    cancel();
    reject(new DOMException("Stopped", "AbortError"));
    await vi.runAllTimersAsync();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
  });
});
