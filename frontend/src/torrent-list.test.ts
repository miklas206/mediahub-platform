import { describe, expect, it } from "vitest";
import { isTorrentPaused, sortTorrents, type Torrent } from "./torrent-list";

function torrent(
  hash: string,
  name: string,
  overrides: Partial<Torrent> = {},
): Torrent {
  return {
    hash,
    name,
    progress: 1,
    state: "stalledUP",
    dlspeed: 0,
    upspeed: 0,
    ratio: 0,
    eta: -1,
    size: 0,
    actionsAllowed: true,
    ...overrides,
  };
}

describe("torrent controls", () => {
  it("offers resume for both legacy paused and current stopped states", () => {
    for (const state of ["pausedDL", "pausedUP", "stoppedDL", "stoppedUP"])
      expect(isTorrentPaused(state)).toBe(true);
    for (const state of [
      "downloading",
      "stalledDL",
      "stalledUP",
      "queuedUP",
      "checkingDL",
    ])
      expect(isTorrentPaused(state)).toBe(false);
  });

  it("sorts numeric values in both directions without changing the polling data", () => {
    const items = [
      torrent("a", "a", { ratio: 10 }),
      torrent("b", "b", { ratio: 2 }),
    ];
    expect(
      sortTorrents(items, "ratio", false).map((item) => item.hash),
    ).toEqual(["b", "a"]);
    expect(sortTorrents(items, "ratio", true).map((item) => item.hash)).toEqual(
      ["a", "b"],
    );
    expect(items.map((item) => item.hash)).toEqual(["a", "b"]);
  });

  it("keeps unknown ETA last in either direction", () => {
    const items = [
      torrent("unknown", "unknown"),
      torrent("infinite", "infinite", { eta: 8640000 }),
      torrent("long", "long", { eta: 120 }),
      torrent("short", "short", { eta: 60 }),
    ];
    expect(sortTorrents(items, "eta", false).map((item) => item.hash)).toEqual([
      "short",
      "long",
      "infinite",
      "unknown",
    ]);
    expect(sortTorrents(items, "eta", true).map((item) => item.hash)).toEqual([
      "long",
      "short",
      "infinite",
      "unknown",
    ]);
  });

  it("sorts episode names naturally and keeps ties stable after polling", () => {
    const a = torrent("a", "Episode 2");
    const b = torrent("b", "Episode 10");
    expect(
      sortTorrents([b, a], "name", false).map((item) => item.hash),
    ).toEqual(["a", "b"]);
    expect(sortTorrents([b, a], "progress", false)).toEqual(
      sortTorrents([a, b], "progress", false),
    );
  });
});
