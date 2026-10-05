import { ArrowUp } from "lucide-react";
import { Link } from "react-router-dom";
import type { AppInfo } from "./contracts";
import type { DashboardData } from "./dashboard-data";
import { bytes } from "./format";
import { t } from "./i18n";
import { isTorrentPaused, type Torrent } from "./torrent-list";
import "./dashboard-torrents.css";

/** Uploading means traffic to peers, not merely a seeding client state. */
export function activeUploads(items?: Torrent[]) {
  if (!items) return undefined;
  const torrents = items
    .filter(
      (item) =>
        Number.isFinite(item.upspeed) &&
        item.upspeed > 0 &&
        !isTorrentPaused(item.state) &&
        !/^(error|missingFiles|unknown)$/i.test(item.state),
    )
    .sort((a, b) => b.upspeed - a.upspeed || a.name.localeCompare(b.name));
  return {
    torrents,
    count: torrents.length,
    speed: torrents.reduce((sum, item) => sum + item.upspeed, 0),
  };
}

export function DashboardUploads({
  apps,
  data,
}: {
  apps?: AppInfo[];
  data: DashboardData;
}) {
  const seedbox = apps?.find((app) => app.packageId === "org.mediahub.seedbox");
  const uploads = !data.torrentError ? activeUploads(data.torrents) : undefined;
  return (
    <section className="panel dashboard-torrents dashboard-uploads">
      <div className="panel-heading">
        <h2>{t("Active uploads")}</h2>
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
          {t("Install Seedbox to see active uploads here.")}
        </p>
      ) : (
        <>
          <div className="dashboard-torrent-totals">
            <span>
              {t("{count} uploading", { count: uploads?.count ?? "—" })}
            </span>
            <span>
              <ArrowUp size={14} aria-hidden="true" />
              {uploads ? bytes(uploads.speed) : "—"}
              {t("/s")}
            </span>
          </div>
          {data.torrentError ? (
            <p role="alert" className="notice">
              {t("Torrent information is unavailable.")}
            </p>
          ) : !uploads ? (
            <p className="muted">{t("Loading torrents…")}</p>
          ) : !uploads.count ? (
            <p className="muted">{t("No active uploads.")}</p>
          ) : (
            uploads.torrents.slice(0, 5).map((item) => (
              <div className="dashboard-torrent" key={item.hash}>
                <strong title={item.name}>{item.name}</strong>
                <div className="dashboard-torrent-detail">
                  <span>
                    {t("Upload")}: {bytes(item.upspeed)}
                    {t("/s")}
                  </span>
                </div>
              </div>
            ))
          )}
          {uploads && uploads.count > 5 && (
            <p className="muted">
              {t("{count} more in Seedbox", { count: uploads.count - 5 })}
            </p>
          )}
        </>
      )}
    </section>
  );
}
