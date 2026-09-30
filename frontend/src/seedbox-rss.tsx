import { useEffect, useState } from "react";
import { api } from "./api";
import { ErrorBox, Panel } from "./phase2";

type Feed = {
  configured: boolean;
  items: { id: string; title: string; published: string }[];
};
export function SeedboxRSS({
  storageId,
  locations,
  onAdded,
}: {
  storageId?: string;
  locations: { id: string; storageLabel?: string }[];
  onAdded: () => void;
}) {
  const [feed, setFeed] = useState<Feed>();
  const [url, setUrl] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [destination, setDestination] = useState("root");
  const [start, setStart] = useState(false);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void api<Feed>("/seedbox/rss", "GET", undefined, controller.signal)
      .then(setFeed)
      .catch(() => {
        if (!controller.signal.aborted)
          setError(
            "RSS is unavailable. Check the MediaHub connection and update Core if necessary.",
          );
      });
    return () => controller.abort();
  }, []);
  async function update(method: string, path: string, data?: unknown) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      setFeed(await api<Feed>(path, method, data));
      setUrl("");
      setSelected([]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function download() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{
        items: { id: string; ok: boolean; state?: string; message?: string }[];
      }>("/seedbox/rss/download", "POST", {
        ids: selected,
        storageId,
        downloadLocationId: destination,
        startImmediately: start,
      });
      const failures = result.items.filter((item) => !item.ok);
      setSelected(failures.map((item) => item.id));
      setNotice(
        `${result.items.filter((item) => item.ok).length} item(s) added or already present. New torrents ${start ? "start after safety checks" : "are stopped; use Resume to download"}.`,
      );
      if (failures.length)
        setError(
          `${failures.length} item(s) could not be added. ${failures[0].message}`,
        );
      onAdded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const visible =
    feed?.items.filter((item) =>
      item.title.toLowerCase().includes(filter.toLowerCase()),
    ) || [];
  return (
    <Panel title="RSS torrents">
      <ErrorBox error={error} />
      {notice && <p role="status">{notice}</p>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void update("POST", "/seedbox/rss", { url });
        }}
      >
        <label>
          Private RSS address (including your RSS key)
          <input
            type="password"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
            autoComplete="off"
            spellCheck={false}
            placeholder={
              feed?.configured
                ? "Feed saved — enter a new address to replace it"
                : "https://tracker.example/rss?key=…"
            }
          />
        </label>
        <p className="muted">
          Copy the complete RSS address from your tracker. MediaHub stores it
          encrypted. Feed and torrent-file requests use MediaHub's connection;
          torrent transfers use the Seedbox VPN. Downloads are selected
          manually.
        </p>
        <div className="button-row">
          <button disabled={busy || !url.trim()}>Save and load feed</button>
          {feed?.configured && (
            <>
              <button
                type="button"
                disabled={busy}
                onClick={() => void update("POST", "/seedbox/rss/refresh")}
              >
                Refresh feed
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void update("DELETE", "/seedbox/rss")}
              >
                Remove feed
              </button>
            </>
          )}
        </div>
      </form>
      {busy && <p role="status">Working…</p>}
      {feed?.configured && (
        <>
          <label>
            Search feed
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Search titles…"
            />
          </label>
          <div style={{ maxHeight: 400, overflowY: "auto" }}>
            {visible.map((item) => (
              <label key={item.id}>
                <input
                  type="checkbox"
                  disabled={
                    busy ||
                    (!selected.includes(item.id) && selected.length >= 20)
                  }
                  checked={selected.includes(item.id)}
                  onChange={(e) =>
                    setSelected((current) =>
                      e.target.checked
                        ? [...current, item.id]
                        : current.filter((id) => id !== item.id),
                    )
                  }
                />
                <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>
                  {item.title}
                  {item.published && (
                    <small style={{ display: "block" }}>{item.published}</small>
                  )}
                </span>
              </label>
            ))}
            {!visible.length && (
              <p>
                No matching torrents in this feed. Up to 200 recent entries are
                shown.
              </p>
            )}
          </div>
          <label>
            Download location
            <select
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
              disabled={busy}
            >
              {locations.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.storageLabel || "Downloads"}
                </option>
              ))}
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={start}
              disabled={busy}
              onChange={(e) => setStart(e.target.checked)}
            />
            Start selected torrents immediately after safety checks
          </label>
          <button
            className="primary"
            disabled={
              busy ||
              !storageId ||
              !selected.length ||
              !locations.some((item) => item.id === destination)
            }
            onClick={() => void download()}
          >
            Add selected ({selected.length}/20)
          </button>
        </>
      )}
    </Panel>
  );
}
