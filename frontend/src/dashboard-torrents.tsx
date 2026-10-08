import { getLocale, t } from "./i18n";

import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp } from "lucide-react";
import { bytes, uptime } from "./format";

import {
  isTorrentPaused,
  torrentStateLabel,
  type Torrent,
} from "./torrent-list";
import type { AppInfo } from "./contracts";
import type { DashboardData } from "./dashboard-data";
import "./dashboard-torrents.css";

export function ongoingTorrents(items: Torrent[]) {
  return items
    .filter(
      (item) =>
        !isTorrentPaused(item.state) &&
        !/^(error|missingFiles|unknown)$/i.test(item.state),
    )
    .sort(
      (a, b) =>
        Number(a.progress >= 1) - Number(b.progress >= 1) ||
        b.dlspeed - a.dlspeed ||
        b.upspeed - a.upspeed ||
        a.name.localeCompare(b.name),
    );
}

export function DashboardTorrents({
  apps,
  data,
}: {
  apps?: AppInfo[];
  data: DashboardData;
}) {
  const seedbox = apps?.find((app) => app.packageId === "org.mediahub.seedbox");
  const items = data.torrents;
  const error = data.torrentError;
  const active = ongoingTorrents(items || []);
  return (
    <section className="panel dashboard-torrents">
      <div className="panel-heading">
        <h2>{t("Ongoing torrents")}</h2>
        {seedbox && (
          <Link
            className="text-link"
            to={`/apps/${seedbox.id}?section=torrents`}
          >
            {t("View torrents")}
          </Link>
        )}
      </div>
      {!apps ? (
        <p className="muted">{t("Loading torrents…")}</p>
      ) : !seedbox ? (
        <p className="muted">
          {t("Install Seedbox to see ongoing torrents here.")}
        </p>
      ) : (
        <>
          {error && (
            <p role="alert" className="notice">
              {t("Torrent information is unavailable.")}
            </p>
          )}
          {items && (
            <div className="dashboard-torrent-totals">
              <span>{t("{count} ongoing", { count: active.length })}</span>
              <span>
                <ArrowDown size={14} aria-hidden="true" />
                {bytes(items.reduce((sum, item) => sum + item.dlspeed, 0))}
                {t("/s")}
              </span>
              <span>
                <ArrowUp size={14} aria-hidden="true" />
                {bytes(items.reduce((sum, item) => sum + item.upspeed, 0))}
                {t("/s")}
              </span>
            </div>
          )}
          {!items && !error && (
            <p className="muted">{t("Loading torrents…")}</p>
          )}
          {items && !error && !active.length && (
            <p className="muted">{t("No ongoing torrents.")}</p>
          )}
          {active.slice(0, 6).map((item) => (
            <div className="dashboard-torrent" key={item.hash}>
              <strong title={item.name}>{item.name}</strong>
              <div className="dashboard-torrent-detail">
                <span>
                  {torrentStateLabel(item.state)} ·{" "}
                  {(item.progress * 100).toLocaleString(getLocale(), {
                    minimumFractionDigits: 1,
                    maximumFractionDigits: 1,
                    useGrouping: false,
                  })}
                  %
                </span>
                <span>
                  {t("Download")}: {bytes(item.dlspeed)}
                  {t("/s · ")}
                  {t("Upload")}: {bytes(item.upspeed)}
                  {t("/s")}
                </span>
                {item.progress < 1 && (
                  <span>
                    {t("Time remaining")}:{" "}
                    {item.eta >= 0 && item.eta < 8640000
                      ? uptime(item.eta)
                      : t("Unknown")}
                  </span>
                )}
              </div>
              <progress
                aria-label={t("Progress of {title}", { title: item.name })}
                value={item.progress}
                max={1}
              />
            </div>
          ))}
          {active.length > 6 && (
            <p className="muted">
              {t("{count} more in Seedbox", { count: active.length - 6 })}
            </p>
          )}
        </>
      )}
    </section>
  );
}
