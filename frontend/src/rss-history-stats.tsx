import { translateText, getLocale, t } from "./i18n";
import { bytes, uptime } from "./format";

import { torrentStateLabel, type Torrent } from "./torrent-list";

type HistoryIdentity = { title: string; torrentHash?: string | null };

export function matchHistoryTorrent(
  item: HistoryIdentity,
  torrents: Torrent[],
): Torrent | undefined {
  const hash = item.torrentHash?.toLowerCase();
  if (hash)
    return torrents.find((torrent) => torrent.hash.toLowerCase() === hash);
  // Legacy history has no hash. Ambiguous names must never show another job's stats.
  const matches = torrents.filter((torrent) => torrent.name === item.title);
  return matches.length === 1 ? matches[0] : undefined;
}

function valid(value: number | null | undefined): value is number {
  return value != null && Number.isFinite(value) && value >= 0;
}

export function historyShareRatio(torrent: Torrent): number | undefined {
  // Relative to content size, including torrents restored without downloading again.
  return valid(torrent.uploaded) && valid(torrent.size) && torrent.size > 0
    ? torrent.uploaded / torrent.size
    : undefined;
}

export function RSSHistoryStats({ torrent }: { torrent?: Torrent }) {
  if (!torrent)
    return (
      <span className="muted rss-history-note">
        {t(
          "Statistics unavailable · Torrent missing or cannot be matched uniquely.",
        )}
      </span>
    );
  const ratio = historyShareRatio(torrent);
  const stats = [
    [t("Size"), valid(torrent.size) ? bytes(torrent.size) : "—"],
    [
      t("Downloaded"),
      valid(torrent.downloaded) ? bytes(torrent.downloaded) : "—",
    ],
    [t("Uploaded"), valid(torrent.uploaded) ? bytes(torrent.uploaded) : "—"],
    [
      t("Share ratio"),
      ratio == null
        ? "—"
        : ratio.toLocaleString(getLocale(), {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          }),
      t("Uploaded divided by content size. 1.00 means one full copy shared."),
    ],
    [
      t("Seeding time"),
      valid(torrent.seeding_time) ? uptime(torrent.seeding_time) : "—",
    ],
    [
      t("Download speed"),
      valid(torrent.dlspeed) ? `${bytes(torrent.dlspeed)}/s` : "—",
    ],
    [
      t("Upload speed"),
      valid(torrent.upspeed) ? `${bytes(torrent.upspeed)}/s` : "—",
    ],
    [
      t("Seeds / peers"),
      `${valid(torrent.num_seeds) ? torrent.num_seeds : "—"} / ${valid(torrent.num_leechs) ? torrent.num_leechs : "—"}`,
    ],
  ];
  return (
    <div className="rss-history-performance">
      <span className="rss-history-state">
        {torrentStateLabel(torrent.state)}
        {valid(torrent.progress) &&
          t(" · {value0}%", {
            value0: Math.round(Math.min(1, torrent.progress) * 100),
          })}
      </span>
      <dl className="rss-history-stats">
        {stats.map(([label, value, explanation]) => (
          <div key={label}>
            <dt title={explanation}>{translateText(label)}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
