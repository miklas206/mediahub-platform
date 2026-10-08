import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiResponseError, downloadBackup } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("API responses during server restarts", () => {
  it.each([200, 502, 503])(
    "handles HTML with status %s without exposing the body or retrying POST",
    async (status) => {
      const fetch = vi.fn().mockResolvedValue(
        new Response("<!DOCTYPE html><p>proxy diagnostic secret</p>", {
          status,
        }),
      );
      vi.stubGlobal("fetch", fetch);
      const error = await api("/updates/platform/install", "POST").catch(
        (error) => error,
      );
      expect(error).toBeInstanceOf(ApiResponseError);
      if (!(error instanceof ApiResponseError))
        throw new Error("Expected API response error");
      expect(error.status).toBe(status);
      expect(error.message).not.toMatch(/DOCTYPE|Unexpected token|secret/);
      expect(fetch).toHaveBeenCalledTimes(1);
    },
  );

  it.each(["", "null", "[]", '{"data":', '{"unexpected":true}'])(
    "rejects malformed or missing envelopes: %s",
    async (body) => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
      await expect(api("/updates/queue")).rejects.toBeInstanceOf(
        ApiResponseError,
      );
    },
  );

  it("accepts the next successful poll after a proxy error", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response("<html>unavailable</html>", { status: 502 }),
      )
      .mockResolvedValueOnce(
        Response.json({ data: { state: "succeeded", progress: 100 } }),
      );
    vi.stubGlobal("fetch", fetch);
    await expect(api("/updates/queue")).rejects.toBeInstanceOf(
      ApiResponseError,
    );
    await expect(api("/updates/queue")).resolves.toEqual({
      state: "succeeded",
      progress: 100,
    });
  });

  it("preserves API error messages and expired-session handling", async () => {
    const dispatchEvent = vi.fn();
    vi.stubGlobal("window", { dispatchEvent });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json(
            { error: { code: "unauthorized", message: "Please sign in" } },
            { status: 401 },
          ),
        ),
    );
    await expect(api("/updates/queue")).rejects.toThrow("Please sign in");
    expect(dispatchEvent.mock.calls[0][0].type).toBe("session-expired");
  });

  it("preserves intentional cancellation while reading a response", async () => {
    const abort = new DOMException("Stopped", "AbortError");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({ status: 200, json: () => Promise.reject(abort) }),
    );
    await expect(api("/updates/queue")).rejects.toBe(abort);
  });

  it("handles HTML backup failures without parsing errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("<html>Bad gateway</html>", { status: 502 }),
        ),
    );
    await expect(downloadBackup({})).rejects.toBeInstanceOf(ApiResponseError);
  });
});
