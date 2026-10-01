import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ErrorBox, Panel } from "./phase2";
import "./rss-feeds.css";
import {
  TorrentRetention,
  defaultRetention,
  type RetentionRule,
} from "./torrent-retention";

type Location = { id: string; storageLabel?: string };
type Feed = {
  retention?: RetentionRule;
  id: string;
  name: string;
  automatic: boolean;
  storageId: string;
  downloadLocationId: string;
  checkedAt: number | null;
  error: string;
  added: number;
  pending: number;
  baselineCount: number;
  items: { id: string; title: string; published: string }[];
};
type Listing = { feeds: Feed[]; intervalSeconds: number };
type Props = {
  storageId?: string;
  locations: Location[];
  onAdded: () => void;
  retentionSupported?: boolean;
};

export function SeedboxRSS(props: Props) {
  const [listing, setListing] = useState<Listing>({
    feeds: [],
    intervalSeconds: 300,
  });
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [destination, setDestination] = useState("root");
  const [automatic, setAutomatic] = useState(false);
  const [retention, setRetention] = useState<RetentionRule>(defaultRetention);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const mutation = useRef(false);
  const generation = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    let loading = false;
    const load = async () => {
      if (mutation.current || loading) return;
      loading = true;
      const version = generation.current;
      try {
        const next = await api<Listing>(
          "/seedbox/rss/feeds",
          "GET",
          undefined,
          controller.signal,
        );
        if (version === generation.current && !controller.signal.aborted)
          setListing(next);
      } catch {
        if (!controller.signal.aborted && version === generation.current)
          setError(
            "RSS feed status is unavailable. Check the connection and Core version.",
          );
      } finally {
        loading = false;
      }
    };
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);
  async function change(path: string, method: string, data?: unknown) {
    mutation.current = true;
    generation.current++;
    setBusy(true);
    setError("");
    try {
      setListing(await api<Listing>(path, method, data));
      props.onAdded();
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  }
  return (
    <Panel title="RSS feeds">
      <ErrorBox error={error} />
      <p>
        Each feed has its own destination. Automatic feeds are checked every
        five minutes, even when this page is closed.
      </p>
      <div className="notice">
        Only future entries download automatically. Entries already present when
        you add a feed or enable automatic downloads are recorded and skipped.
        Older entries and entries without a valid publication date require
        manual selection.
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void change("/seedbox/rss/feeds", "POST", {
            name,
            url,
            automatic,
            retention,
            storageId: props.storageId,
            downloadLocationId: destination,
          }).then((ok) => {
            if (ok) {
              setName("");
              setUrl("");
              setAutomatic(false);
              setRetention(defaultRetention);
            }
          });
        }}
      >
        <label>
          Feed name
          <input
            value={name}
            maxLength={100}
            required
            onChange={(e) => setName(e.target.value)}
            placeholder="For example: Nordic movies"
          />
        </label>
        <label>
          Private RSS address (including RSS key)
          <input
            type="password"
            value={url}
            required
            maxLength={8192}
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Complete https:// RSS address"
          />
        </label>
        <label>
          Destination for this feed
          <select
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
          >
            {props.locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.storageLabel || "Downloads"}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={automatic}
            onChange={(e) => setAutomatic(e.target.checked)}
          />
          Automatically download new entries to this destination
        </label>
        <TorrentRetention
          value={retention}
          onChange={setRetention}
          disabled={busy}
          supported={!!props.retentionSupported}
        />
        <button
          className="primary"
          disabled={
            busy ||
            !props.storageId ||
            !props.locations.some((l) => l.id === destination) ||
            listing.feeds.length >= 20
          }
        >
          Add feed and skip existing entries
        </button>
      </form>
      <p className="muted">
        Up to 20 feeds. Private addresses are stored encrypted. Feed and
        torrent-file requests use MediaHub's connection; torrent transfers use
        the Seedbox VPN.
      </p>
      {busy && <p role="status">Saving or checking feed…</p>}
      {!listing.feeds.length && <p>No feeds saved yet.</p>}
      {listing.feeds.map((feed) => (
        <FeedCard
          key={feed.id}
          feed={feed}
          {...props}
          busy={busy}
          change={change}
        />
      ))}
    </Panel>
  );
}

function FeedCard({
  feed,
  locations,
  storageId,
  onAdded,
  busy,
  retentionSupported,
  change,
}: Props & {
  feed: Feed;
  busy: boolean;
  change: (p: string, m: string, d?: unknown) => Promise<boolean>;
}) {
  const [name, setName] = useState(feed.name);
  const [destination, setDestination] = useState(feed.downloadLocationId);
  const [automatic, setAutomatic] = useState(feed.automatic);
  const [retention, setRetention] = useState<RetentionRule>(
    feed.retention || defaultRetention,
  );
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [start, setStart] = useState(false);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const path = `/seedbox/rss/feeds/${encodeURIComponent(feed.id)}`;
  async function download() {
    setAdding(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ items: { id: string; ok: boolean }[] }>(
        path + "/download",
        "POST",
        { ids: selected, startImmediately: start },
      );
      const failed = result.items.filter((i) => !i.ok);
      setSelected(failed.map((i) => i.id));
      setNotice(
        `${result.items.length - failed.length} added or already present. ${failed.length} failed.${start ? "" : " New torrents are stopped; use Resume to start."}`,
      );
      onAdded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAdding(false);
    }
  }
  return (
    <section
      className="panel rss-feed-card"
      style={{ marginTop: 20, padding: 16 }}
      aria-label={feed.name}
    >
      <h3>{feed.name}</h3>
      <p>
        <strong>
          {feed.automatic
            ? "Automatic downloads enabled"
            : "Manual downloads only"}
        </strong>{" "}
        ·{" "}
        {locations.find((l) => l.id === feed.downloadLocationId)
          ?.storageLabel || "Choose destination"}
      </p>
      <p className="muted">
        Last checked:{" "}
        {feed.checkedAt
          ? new Date(feed.checkedAt * 1000).toLocaleString()
          : "Not checked"}{" "}
        · Added automatically: {feed.added} · Pending: {feed.pending}
      </p>
      <ErrorBox error={feed.error} />
      <ErrorBox error={error} />
      {notice && <p role="status">{notice}</p>}
      <details>
        <summary>Feed settings</summary>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void change(path, "PUT", {
              name,
              automatic,
              retention,
              storageId,
              downloadLocationId: destination,
            });
          }}
        >
          <label>
            Feed name
            <input
              required
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            Download destination
            <select
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
            >
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.storageLabel || "Downloads"}
                </option>
              ))}
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={automatic}
              onChange={(e) => setAutomatic(e.target.checked)}
            />
            Automatically download future entries
          </label>
          <p className="muted">
            Enabling automatic downloads skips everything currently in the feed.
            Disabling clears pending automatic entries; torrents already added
            keep running.
          </p>
          <TorrentRetention
            value={retention}
            onChange={setRetention}
            disabled={busy || adding}
            supported={!!retentionSupported}
          />
          <button
            disabled={
              busy ||
              adding ||
              !storageId ||
              !locations.some((l) => l.id === destination)
            }
          >
            Save feed settings
          </button>
          <p className="muted">
            Cleanup rules apply to future torrents from this feed, including
            manual selections. Change existing torrents using their Cleanup
            button. Removing or disabling a feed does not cancel rules already
            assigned to torrents.
          </p>
        </form>
      </details>
      <div className="button-row">
        <button
          disabled={busy || adding}
          onClick={() => void change(path + "/refresh", "POST")}
        >
          Check feed now
        </button>
        <button
          disabled={busy || adding}
          onClick={() => void change(path, "DELETE")}
        >
          Remove feed
        </button>
      </div>
      <details>
        <summary>
          Browse and select entries manually ({feed.items.length})
        </summary>
        <label>
          Search this feed
          <input value={filter} onChange={(e) => setFilter(e.target.value)} />
        </label>
        <div style={{ maxHeight: 360, overflowY: "auto" }}>
          {feed.items
            .filter((i) => i.title.toLowerCase().includes(filter.toLowerCase()))
            .map((item) => (
              <label key={item.id}>
                <input
                  type="checkbox"
                  disabled={
                    busy ||
                    adding ||
                    (!selected.includes(item.id) && selected.length >= 20)
                  }
                  checked={selected.includes(item.id)}
                  onChange={(e) =>
                    setSelected((ids) =>
                      e.target.checked
                        ? [...ids, item.id]
                        : ids.filter((id) => id !== item.id),
                    )
                  }
                />
                <span style={{ overflowWrap: "anywhere", minWidth: 0 }}>
                  {item.title}
                  <small style={{ display: "block" }}>{item.published}</small>
                </span>
              </label>
            ))}
        </div>
        <label>
          <input
            type="checkbox"
            checked={start}
            onChange={(e) => setStart(e.target.checked)}
          />
          Start manually selected torrents immediately
        </label>
        <button
          disabled={busy || adding || !selected.length || !feed.storageId}
          onClick={() => void download()}
        >
          Add selected ({selected.length}/20)
        </button>
      </details>
    </section>
  );
}
