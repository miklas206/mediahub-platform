import { getLocale, t } from "./i18n";

import { LayoutGroup } from "./page-layout";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { ErrorBox, Panel } from "./phase2";
import { RSSHistoryStats, matchHistoryTorrent } from "./rss-history-stats";
import type { Torrent } from "./torrent-list";
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
  allowOlderItems?: boolean;
  storageId: string;
  downloadLocationId: string;
  checkedAt: number | null;
  error: string;
  added: number;
  automaticHistory?: {
    id: string;
    title: string;
    addedAt: number;
    alreadyPresent: boolean;
    torrentHash?: string | null;
  }[];
  historyUnavailable?: number;
  pending: number;
  baselineCount: number;
  items: { id: string; title: string; published: string }[];
};
type Listing = { feeds: Feed[]; intervalSeconds: number };
type Props = {
  storageId?: string;
  torrents: Torrent[] | null;
  locations: Location[];
  onAdded: () => void;
  retentionSupported?: boolean;
};

export function SeedboxRSS(
  props: Props & {
    addTorrent: ReactNode;
    torrentList: ReactNode;
    overviewCards?: ReactNode;
  },
) {
  const [listing, setListing] = useState<Listing>({
    feeds: [],
    intervalSeconds: 300,
  });
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [destination, setDestination] = useState("root");
  const [automatic, setAutomatic] = useState(false);
  const [allowOlderItems, setAllowOlderItems] = useState(false);
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
            t(
              "RSS feed status is unavailable. Check the connection and Core version.",
            ),
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
    <LayoutGroup
      id="seedbox-torrent-panels"
      className="torrent-panels"
      wideFirst
    >
      {props.overviewCards}
      {props.torrentList}
      <Panel key="feeds" title={t("Your feeds")}>
        <ErrorBox error={error} />
        <p className="muted">
          {t("Automatic feeds are checked every ")}
          {listing.intervalSeconds / 60}{" "}
          {t(
            "minutes, even when this page is closed. Change the interval in Seedbox Settings.",
          )}
        </p>
        <div className="rss-feed-list">
          {" "}
          {busy && <p role="status">{t("Saving or checking feed…")}</p>}
          {!listing.feeds.length && <p>{t("No feeds saved yet.")}</p>}
          {listing.feeds.map((feed) => (
            <FeedCard
              key={feed.id}
              feed={feed}
              {...props}
              busy={busy}
              change={change}
            />
          ))}
        </div>
      </Panel>

      {props.addTorrent}
      <Panel key="add-feed" title={t("Add feed")}>
        <div className="notice">
          {t(
            "By default, automatic downloads require a valid publication date after activation and not in the future. Existing entries and previously seen IDs are skipped. RSS dates are supplied by the tracker and do not prove the original torrent age; use manual downloads if uncertain.",
          )}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void change("/seedbox/rss/feeds", "POST", {
              name,
              url,
              automatic,
              allowOlderItems,
              retention,
              storageId: props.storageId,
              downloadLocationId: destination,
            }).then((ok) => {
              if (ok) {
                setName("");
                setUrl("");
                setAutomatic(false);
                setAllowOlderItems(false);
                setRetention(defaultRetention);
              }
            });
          }}
        >
          <label>
            {t("Feed name")}
            <input
              value={name}
              maxLength={100}
              required
              onChange={(e) => setName(e.target.value)}
              placeholder={t("For example: Nordic movies")}
            />
          </label>
          <label>
            {t("Private RSS address (including RSS key)")}
            <input
              type="password"
              value={url}
              required
              maxLength={8192}
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t("Complete https:// RSS address")}
            />
          </label>
          <label>
            {t("Destination for this feed")}
            <select
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
            >
              {props.locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.storageLabel || t("Downloads")}
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
            {t("Automatically download new entries to this destination")}
          </label>
          <AutomaticDatePolicy
            value={allowOlderItems}
            onChange={setAllowOlderItems}
            disabled={busy}
          />
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
            {t("Add feed and skip existing entries")}
          </button>
        </form>
        <p className="muted">
          {t(
            "Up to 20 feeds. Private addresses are stored encrypted. Feed and torrent-file requests use MediaHub's connection; torrent transfers use the Seedbox VPN.",
          )}
        </p>
      </Panel>
    </LayoutGroup>
  );
}

function FeedCard({
  feed,
  locations,
  storageId,
  onAdded,
  busy,
  retentionSupported,
  torrents,
  change,
}: Props & {
  feed: Feed;
  busy: boolean;
  change: (p: string, m: string, d?: unknown) => Promise<boolean>;
}) {
  const [name, setName] = useState(feed.name);
  const [destination, setDestination] = useState(feed.downloadLocationId);
  const [automatic, setAutomatic] = useState(feed.automatic);
  const [allowOlderItems, setAllowOlderItems] = useState(
    feed.allowOlderItems === true,
  );
  const [retention, setRetention] = useState<RetentionRule>(
    feed.retention || defaultRetention,
  );
  const [filter, setFilter] = useState("");
  const [historyFilter, setHistoryFilter] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [start, setStart] = useState(false);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState<{
    count: number;
    failed: number;
    stopped: boolean;
  } | null>(null);
  const [error, setError] = useState("");
  const path = `/seedbox/rss/feeds/${encodeURIComponent(feed.id)}`;
  async function download() {
    setAdding(true);
    setError("");
    setNotice(null);
    try {
      const result = await api<{ items: { id: string; ok: boolean }[] }>(
        path + "/download",
        "POST",
        { ids: selected, startImmediately: start },
      );
      const failed = result.items.filter((i) => !i.ok);
      setSelected(failed.map((i) => i.id));
      setNotice({
        count: result.items.length - failed.length,
        failed: failed.length,
        stopped: !start,
      });
      onAdded();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAdding(false);
    }
  }
  return (
    <section className="panel rss-feed-card" aria-label={feed.name}>
      <h3>{feed.name}</h3>
      <p>
        <strong>
          {feed.automatic
            ? t("Automatic downloads enabled")
            : t("Manual downloads only")}
        </strong>{" "}
        ·{" "}
        {locations.find((l) => l.id === feed.downloadLocationId)
          ?.storageLabel || t("Choose destination")}
      </p>
      <p className="muted">
        {t("Last checked:")}{" "}
        {feed.checkedAt
          ? new Date(feed.checkedAt * 1000).toLocaleString(getLocale())
          : t("Not checked")}{" "}
        {t("· Added automatically: ")}
        {feed.added}
        {t(" · Pending: ")}
        {feed.pending}
      </p>
      <ErrorBox error={feed.error} />
      <ErrorBox error={error} />
      {notice && (
        <p role="status">
          {t("{count} added or already present. {failed} failed.", {
            count: notice.count,
            failed: notice.failed,
          })}
          {notice.stopped &&
            t(" New torrents are stopped; use Resume to start.")}
        </p>
      )}
      <details>
        <summary>
          {t("Automatic download history (")}
          {feed.added})
        </summary>
        {!!feed.historyUnavailable && (
          <p className="muted rss-history-note">
            {feed.historyUnavailable}
            {t(" earlier additions · No details saved.")}
          </p>
        )}
        {!feed.automaticHistory?.length ? (
          feed.added === 0 && (
            <p className="muted rss-history-note">
              {t("No automatic downloads yet.")}
            </p>
          )
        ) : (
          <>
            <p className="muted rss-history-note">
              {t(
                "Live torrent statistics · Share ratio 1.00 = one full copy uploaded.",
              )}
            </p>
            <label>
              {t("Search automatic download history")}
              <input
                value={historyFilter}
                onChange={(event) => setHistoryFilter(event.target.value)}
              />
            </label>
            <ul className="rss-download-history">
              {feed.automaticHistory
                .filter((item) =>
                  item.title
                    .toLowerCase()
                    .includes(historyFilter.toLowerCase()),
                )
                .map((item) => (
                  <li key={item.id}>
                    <strong>{item.title}</strong>
                    <span className="muted">
                      <time
                        dateTime={new Date(item.addedAt * 1000).toISOString()}
                      >
                        {new Date(item.addedAt * 1000).toLocaleString(
                          getLocale(),
                        )}
                      </time>
                      {" · "}
                      {item.alreadyPresent
                        ? t("Already in torrent client")
                        : t("Added automatically")}
                    </span>
                    <RSSHistoryStats
                      torrent={matchHistoryTorrent(item, torrents ?? [])}
                    />
                  </li>
                ))}
            </ul>
            {!feed.automaticHistory.some((item) =>
              item.title.toLowerCase().includes(historyFilter.toLowerCase()),
            ) && <p>{t("No matching downloads.")}</p>}
          </>
        )}
      </details>
      <details>
        <summary>{t("Feed settings")}</summary>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void change(path, "PUT", {
              name,
              automatic,
              allowOlderItems,
              retention,
              storageId,
              downloadLocationId: destination,
            });
          }}
        >
          <label>
            {t("Feed name")}
            <input
              required
              value={name}
              maxLength={100}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            {t("Download destination")}
            <select
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
            >
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.storageLabel || t("Downloads")}
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
            {t("Automatically download future entries")}
          </label>
          <p className="muted">
            {t(
              "Enabling automatic downloads skips everything currently in the feed. Disabling clears pending automatic entries; torrents already added keep running.",
            )}
          </p>
          <AutomaticDatePolicy
            value={allowOlderItems}
            onChange={setAllowOlderItems}
            disabled={busy}
          />
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
            {t("Save feed settings")}
          </button>
          <p className="muted">
            {t(
              "Cleanup rules apply to future torrents from this feed, including manual selections. Change existing torrents using their Cleanup button. Removing or disabling a feed does not cancel rules already assigned to torrents.",
            )}
          </p>
        </form>
      </details>
      <div className="button-row">
        <button
          disabled={busy || adding}
          onClick={() => void change(path + "/refresh", "POST")}
        >
          {t("Check feed now")}
        </button>
        <button
          disabled={busy || adding}
          onClick={() => void change(path, "DELETE")}
        >
          {t("Remove feed")}
        </button>
      </div>
      <details>
        <summary>
          {t("Browse and select entries manually (")}
          {feed.items.length})
        </summary>
        <label>
          {t("Search this feed")}
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
          {t("Start manually selected torrents immediately")}
        </label>
        <button
          disabled={busy || adding || !selected.length || !feed.storageId}
          onClick={() => void download()}
        >
          {t("Add selected (")}
          {selected.length}/20)
        </button>
      </details>
    </section>
  );
}

function AutomaticDatePolicy({
  value,
  onChange,
  disabled,
}: {
  value: boolean;
  onChange: (value: boolean) => void;
  disabled: boolean;
}) {
  return (
    <>
      <label>
        <input
          type="checkbox"
          checked={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        {t("Allow older or undated newly discovered entries (this feed only)")}
      </label>
      <p className="notice">
        {t(
          "Warning: ignoring publication dates can automatically download large amounts of old torrents from rotating or Freeleech feeds. Leave this off for date protection. Changing this policy fetches a fresh baseline and clears pending entries; it never enables automatic downloads or replays history.",
        )}
      </p>
    </>
  );
}
