import { t } from "./i18n";
import { Fragment, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Brush,
  ArrowUpDown,
  ChevronDown,
  ChevronUp,
  Pause,
  Play,
  RotateCw,
  Trash2,
} from "lucide-react";
import { bytes, uptime } from "./format";
import { retentionModeLabel, type RetentionRule } from "./torrent-retention";

export type Torrent = {
  hash: string;
  name: string;
  progress: number;
  state: string;
  dlspeed: number;
  upspeed: number;
  ratio: number;
  uploaded?: number;
  downloaded?: number;
  eta: number;
  size: number;
  actionsAllowed: boolean;
  num_seeds?: number;
  num_leechs?: number;
  category?: string;
  seeding_time?: number;
  retention?: RetentionRule | null;
  retentionMessage?: string;
};

const sortOptions = [
  ["name", "Name"],
  ["progress", "Progress"],
  ["state", "Status"],
  ["dlspeed", "Download speed"],
  ["upspeed", "Upload speed"],
  ["ratio", "Client ratio"],
  ["eta", "Time remaining"],
  ["size", "Size"],
  ["seeding_time", "Seeding time"],
] as const;
export type TorrentSort = (typeof sortOptions)[number][0];

export function isTorrentPaused(state: string) {
  return /^(paused|stopped)/i.test(state);
}

function hasEta(torrent: Torrent) {
  return (
    Number.isFinite(torrent.eta) && torrent.eta >= 0 && torrent.eta < 8640000
  );
}

export function sortTorrents(
  items: Torrent[],
  key: TorrentSort,
  descending: boolean,
) {
  return [...items].sort((a, b) => {
    // Unknown estimates stay last in either direction.
    if (key === "eta" && hasEta(a) !== hasEta(b)) return hasEta(a) ? -1 : 1;
    const left = key === "eta" && !hasEta(a) ? 0 : (a[key] ?? 0);
    const right = key === "eta" && !hasEta(b) ? 0 : (b[key] ?? 0);
    const comparison =
      typeof left === "string" && typeof right === "string"
        ? left.localeCompare(right, undefined, {
            numeric: true,
            sensitivity: "base",
          })
        : Number(left) - Number(right);
    return (
      (descending ? -comparison : comparison) ||
      a.name.localeCompare(b.name, undefined, {
        numeric: true,
        sensitivity: "base",
      }) ||
      a.hash.localeCompare(b.hash)
    );
  });
}

const stateLabels: Record<string, string> = {
  downloading: "Downloading",
  forcedDL: "Downloading",
  metaDL: "Getting metadata",
  forcedMetaDL: "Getting metadata",
  stalledDL: "Waiting",
  queuedDL: "Queued",
  uploading: "Seeding",
  forcedUP: "Seeding",
  stalledUP: "Seeding · idle",
  queuedUP: "Queued",
  checkingDL: "Checking",
  checkingUP: "Checking",
  checkingResumeData: "Checking",
  moving: "Moving",
  error: "Error",
  missingFiles: "Missing files",
  allocating: "Allocating",
};

export function TorrentList({
  items,
  disabled,
  retentionSupported,
  onAction,
  onCleanup,
}: {
  items: Torrent[] | null;
  disabled: boolean;
  retentionSupported?: boolean;
  onAction: (hash: string, action: string) => void;
  onCleanup: (torrent: Torrent) => void;
}) {
  const [sort, setSort] = useState<TorrentSort>("name");
  const [descending, setDescending] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  function selectSort(key: TorrentSort) {
    if (sort === key) setDescending(!descending);
    else {
      setSort(key);
      setDescending(false);
    }
  }
  const columns: { label: string; key?: TorrentSort }[] = [
    { label: t("Name"), key: "name" },
    { label: t("Progress"), key: "progress" },
    { label: t("Status"), key: "state" },
    { label: t("Transfer"), key: "dlspeed" },
    { label: t("Ratio"), key: "ratio" },
    { label: t("ETA"), key: "eta" },
    { label: t("Size"), key: "size" },
    { label: t("Actions") },
  ];
  const sorted = sortTorrents(items || [], sort, descending);
  return (
    <>
      <div className="torrent-toolbar">
        <span className="muted" role="status">
          {items
            ? t("{count} torrents", { count: items.length })
            : t("Loading torrents…")}
        </span>
        <div className="torrent-sort-controls">
          <label className="torrent-sort-label">
            {t("Sort by")}
            <select
              aria-label={t("Sort by")}
              value={sort}
              onChange={(event) => setSort(event.target.value as TorrentSort)}
            >
              {sortOptions.map(([key, label]) => (
                <option value={key} key={key}>
                  {t(label)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="torrent-icon-button"
            title={descending ? t("Descending order") : t("Ascending order")}
            aria-label={
              descending
                ? t("Descending order; switch to ascending")
                : t("Ascending order; switch to descending")
            }
            onClick={() => setDescending(!descending)}
          >
            {descending ? (
              <ArrowDown size={16} aria-hidden="true" />
            ) : (
              <ArrowUp size={16} aria-hidden="true" />
            )}
          </button>
        </div>
      </div>
      <div
        className="torrent-table-scroll"
        tabIndex={0}
        role="region"
        aria-label={t("Torrent list")}
      >
        <table className="torrent-table">
          <thead>
            <tr>
              {columns.map(({ label, key }) => (
                <th
                  scope="col"
                  key={key || "actions"}
                  aria-sort={
                    key === sort || (key === "dlspeed" && sort === "upspeed")
                      ? descending
                        ? "descending"
                        : "ascending"
                      : undefined
                  }
                >
                  {key === "dlspeed" ? (
                    <div className="torrent-transfer-sorts">
                      <button
                        type="button"
                        className="torrent-column-sort"
                        title={t("Sort by download speed")}
                        aria-label={t("Sort by download speed")}
                        onClick={() => selectSort("dlspeed")}
                      >
                        <ArrowDown size={12} aria-hidden="true" />
                        {t(" Download ")}
                        {sort === "dlspeed" &&
                          (descending ? (
                            <ArrowDown size={12} aria-hidden="true" />
                          ) : (
                            <ArrowUp size={12} aria-hidden="true" />
                          ))}
                      </button>
                      <button
                        type="button"
                        className="torrent-column-sort"
                        title={t("Sort by upload speed")}
                        aria-label={t("Sort by upload speed")}
                        onClick={() => selectSort("upspeed")}
                      >
                        <ArrowUp size={12} aria-hidden="true" />
                        {t(" Upload ")}
                        {sort === "upspeed" &&
                          (descending ? (
                            <ArrowDown size={12} aria-hidden="true" />
                          ) : (
                            <ArrowUp size={12} aria-hidden="true" />
                          ))}
                      </button>
                    </div>
                  ) : key ? (
                    <button
                      type="button"
                      className="torrent-column-sort"
                      onClick={() => selectSort(key)}
                    >
                      {t(label)}
                      {key === sort ? (
                        descending ? (
                          <ArrowDown size={12} aria-hidden="true" />
                        ) : (
                          <ArrowUp size={12} aria-hidden="true" />
                        )
                      ) : (
                        <ArrowUpDown size={12} aria-hidden="true" />
                      )}
                    </button>
                  ) : (
                    label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((torrent) => {
              const paused = isTorrentPaused(torrent.state);
              const showDetails = expanded === torrent.hash;
              const blocked = disabled || !torrent.actionsAllowed;
              const cleanup = torrent.retention
                ? t("Cleanup: {mode} · {action}", {
                    mode: retentionModeLabel(torrent.retention.mode),
                    action:
                      torrent.retention.action === "delete_files"
                        ? t("deletes files")
                        : t("keeps files"),
                  })
                : t("Cleanup settings");
              return (
                <Fragment key={torrent.hash}>
                  <tr>
                    <td className="torrent-name">
                      <span className="torrent-title" title={torrent.name}>
                        {torrent.name}
                      </span>
                    </td>
                    <td className="torrent-progress">
                      <progress
                        max={1}
                        value={torrent.progress}
                        aria-label={t("{name} progress", {
                          name: torrent.name,
                        })}
                      />
                      <small>{(torrent.progress * 100).toFixed(1)}%</small>
                    </td>
                    <td>
                      <span className="torrent-state" title={torrent.state}>
                        {paused
                          ? t("Paused")
                          : t(stateLabels[torrent.state] || torrent.state)}
                      </span>
                    </td>
                    <td>
                      <div className="torrent-transfer">
                        <span title={t("Download speed")}>
                          <ArrowDown size={12} aria-hidden="true" />
                          <span className="sr-only">{t("Download: ")}</span>
                          {bytes(torrent.dlspeed)}/s
                        </span>
                        <span title={t("Upload speed")}>
                          <ArrowUp size={12} aria-hidden="true" />
                          <span className="sr-only">{t("Upload: ")}</span>
                          {bytes(torrent.upspeed)}/s
                        </span>
                      </div>
                    </td>
                    <td
                      title={t(
                        "qBittorrent upload/download history. Tracker totals may differ.",
                      )}
                    >
                      {torrent.ratio.toFixed(2)}
                    </td>
                    <td>{hasEta(torrent) ? uptime(torrent.eta) : "—"}</td>
                    <td>{bytes(torrent.size)}</td>
                    <td>
                      <div className="torrent-actions">
                        <button
                          type="button"
                          className="torrent-icon-button"
                          disabled={blocked}
                          title={paused ? t("Resume") : t("Pause")}
                          aria-label={`${paused ? t("Resume") : t("Pause")} ${torrent.name}`}
                          onClick={() =>
                            onAction(torrent.hash, paused ? "resume" : "pause")
                          }
                        >
                          {paused ? (
                            <Play size={16} aria-hidden="true" />
                          ) : (
                            <Pause size={16} aria-hidden="true" />
                          )}
                        </button>
                        <button
                          type="button"
                          className="torrent-icon-button"
                          disabled={blocked}
                          title={t("Recheck downloaded files")}
                          aria-label={t("Recheck {name}", {
                            name: torrent.name,
                          })}
                          onClick={() => onAction(torrent.hash, "recheck")}
                        >
                          <RotateCw size={16} aria-hidden="true" />
                        </button>
                        {retentionSupported && (
                          <button
                            type="button"
                            className="torrent-icon-button"
                            disabled={blocked}
                            title={cleanup}
                            aria-label={t("Cleanup settings for {name}", {
                              name: torrent.name,
                            })}
                            onClick={() => onCleanup(torrent)}
                          >
                            <Brush size={16} aria-hidden="true" />
                          </button>
                        )}
                        <button
                          type="button"
                          className="torrent-icon-button torrent-remove"
                          disabled={blocked}
                          title={t("Remove job · keep files")}
                          aria-label={t("Remove job {name}; keep files", {
                            name: torrent.name,
                          })}
                          onClick={() => onAction(torrent.hash, "remove")}
                        >
                          <Trash2 size={16} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          className="torrent-icon-button"
                          title={
                            showDetails ? t("Hide details") : t("Show details")
                          }
                          aria-label={t(
                            showDetails
                              ? "Hide details for {name}"
                              : "Show details for {name}",
                            { name: torrent.name },
                          )}
                          aria-expanded={showDetails}
                          aria-controls={`torrent-details-${torrent.hash}`}
                          onClick={() =>
                            setExpanded(showDetails ? null : torrent.hash)
                          }
                        >
                          {showDetails ? (
                            <ChevronUp size={16} aria-hidden="true" />
                          ) : (
                            <ChevronDown size={16} aria-hidden="true" />
                          )}
                        </button>
                      </div>
                    </td>
                  </tr>
                  {showDetails && (
                    <tr
                      className="torrent-details-row"
                      id={`torrent-details-${torrent.hash}`}
                    >
                      <td colSpan={8}>
                        <strong className="torrent-full-name">
                          {torrent.name}
                        </strong>
                        <div className="torrent-details">
                          <span>
                            {torrent.num_seeds ?? 0}
                            {t(" seeds ·")} {torrent.num_leechs ?? 0}
                            {t(" peers")}
                          </span>
                          {torrent.category && (
                            <span>
                              {t("Category: ")}
                              {torrent.category}
                            </span>
                          )}
                          {!!torrent.seeding_time && (
                            <span>
                              {t("Seeded ")}
                              {uptime(torrent.seeding_time)}
                            </span>
                          )}
                          {typeof torrent.uploaded === "number" &&
                            typeof torrent.downloaded === "number" && (
                              <span>
                                {bytes(torrent.uploaded)}
                                {t(" uploaded /")} {bytes(torrent.downloaded)}
                                {t(" downloaded")}
                              </span>
                            )}
                          {torrent.retention && <span>{cleanup}</span>}
                        </div>
                        {torrent.retentionMessage && (
                          <p
                            role="status"
                            className="torrent-retention-message"
                          >
                            {t(torrent.retentionMessage)}
                          </p>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
