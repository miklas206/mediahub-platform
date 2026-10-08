import { useCallback, useEffect, useSyncExternalStore } from "react";
import { api } from "./api";
import { serviceSnapshots } from "./service-snapshots";
import type { Runtime } from "./runtime";

export type RuntimeSnapshot = {
  view: string;
  report: Runtime;
  operatorUrl?: string;
};
export function useServiceSnapshot<T>(
  kind: "runtime" | "recent",
  appId: string,
  interval: number,
) {
  const key = `${kind}:${appId}`;
  const snapshot = useSyncExternalStore(serviceSnapshots.subscribe, () =>
    serviceSnapshots.get<T>(key),
  );
  useEffect(
    () =>
      serviceSnapshots.acquire(key, interval, (signal) =>
        api<T>(
          `/apps/${encodeURIComponent(appId)}/${kind === "runtime" ? "runtime" : "plex/recent-media"}`,
          "GET",
          undefined,
          signal,
        ),
      ),
    [key, appId, kind, interval],
  );
  const reload = useCallback(() => {
    void serviceSnapshots.refresh(key);
  }, [key]);
  // Age is also checked synchronously on navigation, before the effect refreshes.
  const stale =
    snapshot.stale ||
    Date.now() - (snapshot.updatedAt ?? -Infinity) >= interval;
  return { ...snapshot, stale, reload };
}

export function useRuntimeSnapshot(appId: string) {
  return useServiceSnapshot<RuntimeSnapshot>("runtime", appId, 10000);
}
