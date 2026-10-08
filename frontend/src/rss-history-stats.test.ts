import { describe, expect, it } from "vitest";
import { historyShareRatio, matchHistoryTorrent } from "./rss-history-stats";
import type { Torrent } from "./torrent-list";

const torrent: Torrent = {
  hash: "a".repeat(40),
  name: "Release",
  state: "uploading",
  progress: 1,
  size: 1000,
  downloaded: 0,
  uploaded: 2000,
  ratio: 0,
  dlspeed: 0,
  upspeed: 20,
  eta: 0,
  actionsAllowed: true,
};

describe("RSS history torrent identity", () => {
  it("uses the hash even if the client renamed the torrent", () => {
    expect(
      matchHistoryTorrent(
        { title: "Old title", torrentHash: torrent.hash.toUpperCase() },
        [torrent],
      ),
    ).toBe(torrent);
  });
  it("does not fall back to another job with the same title when a known hash is missing", () => {
    expect(
      matchHistoryTorrent(
        { title: torrent.name, torrentHash: "b".repeat(40) },
        [torrent],
      ),
    ).toBeUndefined();
  });
  it("matches legacy rows only by one exact name", () => {
    expect(matchHistoryTorrent({ title: torrent.name }, [torrent])).toBe(
      torrent,
    );
    expect(
      matchHistoryTorrent({ title: torrent.name }, [
        torrent,
        { ...torrent, hash: "b".repeat(40) },
      ]),
    ).toBeUndefined();
    expect(matchHistoryTorrent({ title: "Other" }, [torrent])).toBeUndefined();
  });
});

describe("RSS history share ratio", () => {
  it("measures copies shared even if restored content has zero downloaded bytes", () => {
    expect(historyShareRatio(torrent)).toBe(2);
    expect(historyShareRatio({ ...torrent, uploaded: 0 })).toBe(0);
  });
  it("does not invent statistics for missing or invalid counters", () => {
    expect(
      historyShareRatio({ ...torrent, uploaded: undefined }),
    ).toBeUndefined();
    expect(historyShareRatio({ ...torrent, uploaded: -1 })).toBeUndefined();
    expect(historyShareRatio({ ...torrent, size: 0 })).toBeUndefined();
    expect(
      historyShareRatio({ ...torrent, uploaded: Infinity }),
    ).toBeUndefined();
  });
});
