import { useEffect, useState } from "react";
import { api } from "./api";
import type { Storage } from "./contracts";
import type { Torrent } from "./torrent-list";

export type DashboardData = {
  storage?: Storage[];
  storageError?: boolean;
  torrents?: Torrent[];
  torrentError?: boolean;
  country?: string;
};

/** Share the dashboard's read-only observations across overview and detail cards. */
export function useDashboardData(seedboxId?: string) {
  const [data, setData] = useState<DashboardData>({});
  useEffect(() => {
    const controller = new AbortController();
    let loading = false;
    async function refresh() {
      if (loading || document.hidden) return;
      loading = true;
      const [storage, torrents, location] = await Promise.allSettled([
        api<Storage[]>(
          "/storage/locations",
          "GET",
          undefined,
          controller.signal,
        ),
        seedboxId
          ? api<{ items: Torrent[] }>(
              "/seedbox/torrents",
              "GET",
              undefined,
              controller.signal,
            )
          : Promise.resolve(undefined),
        seedboxId
          ? api<{ current?: { country?: string } }>(
              "/seedbox/locations",
              "GET",
              undefined,
              controller.signal,
            )
          : Promise.resolve(undefined),
      ]);
      if (!controller.signal.aborted)
        setData({
          storage:
            storage.status === "fulfilled" && Array.isArray(storage.value)
              ? storage.value
              : undefined,
          storageError: storage.status === "rejected",
          torrents:
            torrents.status === "fulfilled" ? torrents.value?.items : undefined,
          torrentError: torrents.status === "rejected",
          country:
            location.status === "fulfilled"
              ? location.value?.current?.country
              : undefined,
        });
      loading = false;
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [seedboxId]);
  return data;
}

/** Follow StorageSummary's shared-filesystem grouping so aliases are not added twice. */
export function mediaCapacity(locations?: Storage[]) {
  const volumes = new Map<string, { total: number; free: number }>();
  for (const location of locations || []) {
    if (
      !location.exists ||
      !location.readable ||
      !location.writable ||
      location.error ||
      !["media", "movies", "tv", "downloads"].includes(location.kind)
    )
      continue;
    if (
      location.totalBytes == null ||
      location.freeBytes == null ||
      !Number.isFinite(location.totalBytes) ||
      !Number.isFinite(location.freeBytes) ||
      location.totalBytes <= 0
    )
      continue;
    const key = [
      location.filesystem || "unknown",
      location.totalBytes,
      location.freeBytes,
    ].join(":");
    volumes.set(key, {
      total: location.totalBytes,
      free: Math.max(0, Math.min(location.totalBytes, location.freeBytes)),
    });
  }
  if (!volumes.size) return undefined;
  const total = [...volumes.values()].reduce((sum, v) => sum + v.total, 0);
  const free = [...volumes.values()].reduce((sum, v) => sum + v.free, 0);
  return {
    total,
    free,
    used: total - free,
    percent: ((total - free) / total) * 100,
    volumes: volumes.size,
  };
}
