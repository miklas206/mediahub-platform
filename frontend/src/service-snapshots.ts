export type Snapshot<T = unknown> = {
  data?: T;
  updatedAt?: number;
  stale: boolean;
  error: string;
  refreshing: boolean;
};
type Entry = {
  snapshot: Snapshot;
  users: number;
  controller?: AbortController;
  timer?: ReturnType<typeof setInterval>;
  expiry?: ReturnType<typeof setTimeout>;
  load: (signal: AbortSignal) => Promise<unknown>;
  interval: number;
  visibility?: () => void;
};
const empty: Snapshot = { stale: true, error: "", refreshing: false };

// Memory only: auth transitions invalidate both observations and in-flight work.
export class ServiceSnapshots {
  private entries = new Map<string, Entry>();
  private listeners = new Set<() => void>();
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private version = 0;
  getVersion = () => this.version;
  private emit() {
    this.version++;
    for (const listener of this.listeners) listener();
  }
  get<T>(key: string): Snapshot<T> {
    return (this.entries.get(key)?.snapshot || empty) as Snapshot<T>;
  }
  private stop(entry: Entry) {
    entry.controller?.abort();
    entry.controller = undefined;
    clearInterval(entry.timer);
    clearTimeout(entry.expiry);
    entry.expiry = undefined;
    entry.timer = undefined;
    if (entry.visibility && typeof document !== "undefined")
      document.removeEventListener("visibilitychange", entry.visibility);
    entry.visibility = undefined;
    entry.snapshot = { ...entry.snapshot, refreshing: false };
  }
  clear() {
    for (const entry of this.entries.values()) this.stop(entry);
    this.entries.clear();
    this.emit();
  }
  prune(ids: string[]) {
    const allowed = new Set(ids);
    for (const [key, entry] of this.entries) {
      if (!allowed.has(key.slice(key.indexOf(":") + 1))) {
        this.stop(entry);
        this.entries.delete(key);
      }
    }
    this.emit();
  }
  acquire(key: string, interval: number, load: Entry["load"]) {
    let entry = this.entries.get(key);
    if (!entry) {
      // Limit retained inactive observations, without evicting mounted consumers.
      if (this.entries.size >= 64) {
        const inactive = [...this.entries].find(([, value]) => !value.users);
        if (inactive) this.entries.delete(inactive[0]);
      }
      entry = { snapshot: empty, users: 0, interval, load };
      this.entries.set(key, entry);
    }
    entry.users++;
    if (!entry.timer) {
      const refresh = () => {
        if (typeof document !== "undefined" && document.hidden) return;
        const age = Date.now() - (entry.snapshot.updatedAt ?? -Infinity);
        if (entry.snapshot.stale || age >= interval) void this.refresh(key);
      };
      entry.timer = setInterval(() => void this.refresh(key), interval);
      entry.visibility = refresh;
      if (typeof document !== "undefined")
        document.addEventListener("visibilitychange", refresh);
      refresh();
      if (entry.snapshot.data && !entry.snapshot.stale) this.expire(key, entry);
    }
    const current = entry;
    return () => {
      current.users--;
      if (!current.users) {
        this.stop(current);
        if (this.entries.size > 64 && this.entries.get(key) === current)
          this.entries.delete(key);
        this.emit();
      }
    };
  }
  private expire(key: string, entry: Entry) {
    clearTimeout(entry.expiry);
    entry.expiry = setTimeout(
      () => {
        if (this.entries.get(key) !== entry) return;
        entry.snapshot = { ...entry.snapshot, stale: true };
        this.emit();
      },
      Math.max(
        0,
        entry.interval - (Date.now() - (entry.snapshot.updatedAt ?? 0)),
      ),
    );
  }
  async refresh(key: string) {
    const entry = this.entries.get(key);
    if (
      !entry ||
      entry.controller ||
      !entry.users ||
      (typeof document !== "undefined" && document.hidden)
    )
      return;
    const controller = new AbortController();
    entry.controller = controller;
    entry.snapshot = {
      ...entry.snapshot,
      refreshing: true,
      stale:
        entry.snapshot.stale ||
        Date.now() - (entry.snapshot.updatedAt ?? -Infinity) >= entry.interval,
    };
    this.emit();
    try {
      const data = await entry.load(controller.signal);
      if (controller.signal.aborted || this.entries.get(key) !== entry) return;
      entry.snapshot = {
        data,
        updatedAt: Date.now(),
        stale: false,
        error: "",
        refreshing: false,
      };
      this.expire(key, entry);
    } catch (error) {
      if (controller.signal.aborted || this.entries.get(key) !== entry) return;
      entry.snapshot = {
        ...entry.snapshot,
        stale: true,
        refreshing: false,
        error:
          error instanceof Error
            ? error.message
            : "Service temporarily unavailable",
      };
    } finally {
      if (!controller.signal.aborted && this.entries.get(key) === entry) {
        entry.controller = undefined;
        this.emit();
      }
    }
  }
}
export const serviceSnapshots = new ServiceSnapshots();
