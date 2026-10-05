import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  isTorrentPaused,
  readTorrentSort,
  sortTorrents,
  torrentSeedingTime,
  TorrentList,
  type Torrent,
} from "./torrent-list";

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
  it("shows seed time in collapsed torrent rows without opening details", () => {
    const html = renderToStaticMarkup(
      createElement(TorrentList, {
        items: [
          torrent("seed", "Seed", { seeding_time: 90000 }),
          torrent("zero", "Zero", { seeding_time: 0 }),
          torrent("unknown", "Unknown"),
        ],
        disabled: false,
        onAction: () => {},
        onCleanup: () => {},
      }),
    );
    expect(html).toContain("Seeding time: 1d 1h");
    expect(html).toContain("Seeding time: 0h 0m");
    expect(html).toContain("Seeding time: —");
    expect(html).not.toContain('class="torrent-details-row"');
  });
  it("formats actual accumulated seed time including zero and missing values", () => {
    expect(torrentSeedingTime(0)).toBe("0h 0m");
    expect(torrentSeedingTime(3660)).toBe("1h 1m");
    expect(torrentSeedingTime(25 * 3600)).toBe("1d 1h");
    for (const value of [undefined, -1, NaN, Infinity])
      expect(torrentSeedingTime(value)).toBe("—");
  });

  it("sorts torrents by accumulated seeding time", () => {
    const rows = [
      torrent("short", "Short", { seeding_time: 60 }),
      torrent("long", "Long", { seeding_time: 90000 }),
    ];
    expect(
      sortTorrents(rows, "seeding_time", true).map((row) => row.hash),
    ).toEqual(["long", "short"]);
  });
  it("restores saved sorting and direction and rejects invalid preferences", () => {
    expect(readTorrentSort('{"key":"added_on","descending":true}')).toEqual({
      key: "added_on",
      descending: true,
    });
    expect(readTorrentSort('{"key":"ratio","descending":false}')).toEqual({
      key: "ratio",
      descending: false,
    });
    for (const raw of [
      null,
      "bad",
      "null",
      '{"key":"invalid","descending":true}',
      '{"key":"name","descending":"false"}',
    ])
      expect(readTorrentSort(raw)).toEqual({ key: "name", descending: false });
  });
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

  it("sorts by date added with newest first in descending order", () => {
    const items = [
      torrent("old", "Old", { added_on: 100 }),
      torrent("new", "New", { added_on: 200 }),
      torrent("missing", "Missing", { added_on: null }),
    ];
    expect(
      sortTorrents(items, "added_on", true).map((item) => item.hash),
    ).toEqual(["new", "old", "missing"]);
    expect(
      sortTorrents(items, "added_on", false).map((item) => item.hash),
    ).toEqual(["missing", "old", "new"]);
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
