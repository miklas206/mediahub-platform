import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  isTorrentPaused,
  readTorrentSort,
  sortTorrents,
  torrentSeedingTime,
  torrentPopularity,
  TorrentList,
  type Torrent,
} from "./torrent-list";

import { setLanguage } from "./i18n";

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
  it("renders a sortable popularity column including zero and unknown values", () => {
    const html = renderToStaticMarkup(
      createElement(TorrentList, {
        items: [
          torrent("popular", "Popular", { popularity: 1.234 }),
          torrent("zero", "Zero", { popularity: 0 }),
          torrent("unknown", "Unknown"),
          torrent("invalid", "Invalid", { popularity: Infinity }),
        ],
        disabled: false,
        onAction: () => {},
        onCleanup: () => {},
      }),
    );
    expect(html).toContain('<option value="popularity">Popularity</option>');
    expect(html).toContain('data-label="Popularity">1.23</td>');
    expect(html).toContain('data-label="Popularity">0.00</td>');
    expect(html.match(/data-label="Popularity">—<\/td>/g)).toHaveLength(2);
  });

  it("formats popularity with two localized decimals, not derived from ratio", () => {
    expect(torrentPopularity(0)).toBe("0.00");
    expect(torrentPopularity(1.234)).toBe("1.23");
    for (const value of [undefined, null, NaN, Infinity, -Infinity, "2", true])
      expect(torrentPopularity(value)).toBe("—");
    try {
      setLanguage("da");
      expect(torrentPopularity(0)).toBe("0,00");
      const html = renderToStaticMarkup(
        createElement(TorrentList, {
          items: [torrent("zero", "Zero", { popularity: 0 })],
          disabled: false,
          onAction: () => {},
          onCleanup: () => {},
        }),
      );
      expect(html).toContain('data-label="Popularitet">0,00</td>');
      expect(html).toContain('<option value="popularity">Popularitet</option>');
    } finally {
      setLanguage("en");
    }
  });

  it("sorts popularity numerically with unknowns last in both directions", () => {
    const rows = [
      torrent("missing", "Missing"),
      torrent("null", "Null", { popularity: null }),
      torrent("invalid", "Invalid", { popularity: NaN }),
      torrent("zero", "Zero", { popularity: 0 }),
      torrent("low", "Low", { popularity: 2 }),
      torrent("high", "High", { popularity: 10 }),
    ];
    expect(
      sortTorrents(rows, "popularity", false).map((row) => row.hash),
    ).toEqual(["zero", "low", "high", "invalid", "missing", "null"]);
    expect(
      sortTorrents(rows, "popularity", true).map((row) => row.hash),
    ).toEqual(["high", "low", "zero", "invalid", "missing", "null"]);
    expect(rows[0].hash).toBe("missing");
    expect(readTorrentSort('{"key":"popularity","descending":true}')).toEqual({
      key: "popularity",
      descending: true,
    });
  });
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
