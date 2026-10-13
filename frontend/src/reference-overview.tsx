import { useEffect } from "react";
import { Link } from "react-router-dom";
import {
  Check,
  Cpu,
  MemoryStick,
  HardDrive,
  File,
  Activity as Pulse,
} from "lucide-react";
import type { Metrics, AppInfo, Activity } from "./contracts";
import type { DashboardData } from "./dashboard-data";
import { mediaCapacity } from "./dashboard-data";
import { effectiveServiceStatus, type Reports } from "./control-center";
import { useAppOverview, overviewEntry, overviewHealth } from "./app-overview";
import { ServiceIcon } from "./service-icon";
import { bytes, uptime } from "./format";
import { t, translateText, getLocale } from "./i18n";
import { useData } from "./use-data";

export function ReferenceOverview({
  metrics,
  apps,
  reports,
  dashboard,
  live,
  failed,
}: {
  metrics: Metrics;
  apps?: AppInfo[];
  reports: Reports;
  dashboard: DashboardData;
  live: boolean;
  failed: boolean;
}) {
  const managed = useAppOverview(
    !!apps?.some((app) =>
      /org\.mediahub\.(mediaseed|mediavpn)$/.test(app.packageId),
    ),
  );
  const events = useData<Activity[]>("/events/history");
  const reload = events.reload;
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) reload();
    }, 30000);
    return () => window.clearInterval(timer);
  }, [reload]);
  const state = (app: AppInfo) =>
    !live || failed
      ? "unknown"
      : /org\.mediahub\.(mediaseed|mediavpn)$/.test(app.packageId)
        ? overviewHealth(overviewEntry(managed, app.packageId))
        : effectiveServiceStatus(app, reports[app.id], live, failed);
  const states = (apps || []).filter((app) => !app.isMock).map(state);
  const healthy = states.filter((value) => value === "healthy").length;
  const allHealthy =
    live &&
    !failed &&
    !!states.length &&
    states.every((value) => value === "healthy");
  const capacity =
    live && !dashboard.storageError
      ? mediaCapacity(dashboard.storage)
      : undefined;
  const measurements = [
    {
      name: "CPU",
      icon: Cpu,
      value:
        live && metrics.cpu.percent != null
          ? `${metrics.cpu.percent.toFixed(1)}%`
          : "\u2014",
      percent: live ? metrics.cpu.percent : null,
    },
    {
      name: "RAM",
      icon: MemoryStick,
      value: live
        ? `${bytes(metrics.ram.usedBytes)} / ${bytes(metrics.ram.totalBytes)}`
        : "\u2014",
      percent: live ? metrics.ram.percent : null,
    },
    {
      name: capacity ? "Storage" : "Core storage",
      icon: HardDrive,
      value: live
        ? `${bytes(capacity?.used ?? metrics.disk.usedBytes)} / ${bytes(capacity?.total ?? metrics.disk.totalBytes)}`
        : "\u2014",
      percent: live ? (capacity?.percent ?? metrics.disk.percent) : null,
    },
  ];
  const seed = overviewEntry(managed, "org.mediahub.mediaseed");
  const torrentData =
    live &&
    !failed &&
    seed?.status === "ok" &&
    seed.data &&
    Date.now() / 1000 - seed.data.checkedAt <= 30
      ? seed.data.torrents
      : live && !failed && !dashboard.torrentError
        ? dashboard.torrents
        : undefined;
  const activeTorrents = torrentData?.filter(
    (row) =>
      row.progress < 1 && !/stopped|paused|error|missing/i.test(row.state),
  );
  const downloads = activeTorrents?.slice(0, 4);
  const seedApp = apps?.find((app) =>
    /org\.mediahub\.(mediaseed|seedbox)$/.test(app.packageId),
  );
  const seedUrl = seedApp?.openUrl || seedApp?.externalUrl;
  return (
    <div className="reference-overview">
      <section className="overview-status" aria-label={t("System status")}>
        <span
          className={`overview-status-icon ${allHealthy ? "healthy" : "unknown"}`}
        >
          {allHealthy ? <Check size={18} /> : <Pulse size={18} />}
        </span>
        <div>
          <strong>
            {t(
              allHealthy
                ? "All systems operational"
                : !live || failed
                  ? "Status unavailable"
                  : states.length
                    ? "Check service status"
                    : "Core online",
            )}
          </strong>
          <small>
            {t(
              allHealthy
                ? "Everything is running smoothly."
                : "Live status from your MediaHub installation.",
            )}
          </small>
        </div>
        <div className="overview-uptime">
          <small>{t("Core uptime")}</small>
          <strong>{live ? uptime(metrics.coreUptimeSeconds) : "\u2014"}</strong>
        </div>
      </section>
      <div className="overview-resource-row">
        {measurements.map((item) => (
          <article key={item.name}>
            <item.icon size={23} />
            <div>
              <small>{t(item.name)}</small>
              <strong>{item.value}</strong>
              <progress
                aria-label={t(item.name)}
                max={100}
                value={
                  item.percent == null
                    ? undefined
                    : Math.max(0, Math.min(100, item.percent))
                }
              />
            </div>
          </article>
        ))}
      </div>
      <div className="overview-columns">
        <section>
          <header>
            <div>
              <h2>{t("Connected apps")}</h2>
              <small>
                {apps && !failed && live
                  ? `${healthy} / ${states.length} ${t("Running")}`
                  : t("Status unavailable")}
              </small>
            </div>
            <Link to="/">{t("View all")} &rarr;</Link>
          </header>
          <div className="overview-connected">
            {(apps || [])
              .filter((app) => !app.isMock)
              .map((app) => {
                const content = (
                  <>
                    <ServiceIcon packageId={app.packageId} size={26} />
                    <span>
                      <strong>{app.name}</strong>
                      <small className={state(app)}>
                        {t(
                          state(app) === "healthy"
                            ? "Running"
                            : state(app) === "unknown"
                              ? "Status unavailable"
                              : "Check connection",
                        )}
                      </small>
                    </span>
                  </>
                );
                return app.openUrl || app.externalUrl ? (
                  <a
                    key={app.id}
                    href={app.openUrl || app.externalUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {content}
                  </a>
                ) : (
                  <Link key={app.id} to={app.detailPath || `/apps/${app.id}`}>
                    {content}
                  </Link>
                );
              })}
            {!apps?.length && (
              <p className="muted">
                {t(failed ? "Status unavailable" : "No apps installed")}
              </p>
            )}
          </div>
        </section>
        <section>
          <header>
            <div>
              <h2>{t("Active downloads")}</h2>
              <small>
                {downloads
                  ? `${activeTorrents!.length} ${t("Downloading")}`
                  : t("Waiting for service status")}
              </small>
            </div>
            {seedUrl ? (
              <a href={seedUrl} target="_blank" rel="noopener noreferrer">
                {t("View all")} &rarr;
              </a>
            ) : (
              <Link
                to={
                  seedApp
                    ? `${seedApp.detailPath || `/apps/${seedApp.id}`}?section=torrents`
                    : "/"
                }
              >
                {t("View all")} &rarr;
              </Link>
            )}
          </header>
          <div className="overview-downloads">
            {downloads?.map((row) => (
              <article key={row.hash}>
                <File size={18} />
                <div>
                  <strong>{row.name}</strong>
                  <progress
                    aria-label={`${t("Progress")}: ${row.name}`}
                    max={1}
                    value={row.progress}
                  />
                </div>
                <small>{Math.round(row.progress * 100)}%</small>
                <small>{bytes(row.dlspeed)}/s</small>
              </article>
            ))}
            {!downloads?.length && (
              <p className="muted">
                {t(downloads ? "No active downloads" : "Status unavailable")}
              </p>
            )}
          </div>
        </section>
      </div>
      <section className="overview-activity">
        <header>
          <h2>{t("Recent activity")}</h2>
          <Link to="/settings?section=Activity">{t("View all")} &rarr;</Link>
        </header>
        {events.data?.slice(0, 5).map((event) => (
          <div key={event.id}>
            <Pulse size={15} />
            <strong>{event.source}</strong>
            <span>{translateText(event.message)}</span>
            <time dateTime={event.timestamp}>
              {new Date(event.timestamp).toLocaleTimeString(getLocale(), {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </time>
          </div>
        ))}
        {!events.data?.length && (
          <p className="muted">
            {t(
              events.error
                ? "Status unavailable"
                : "Activity will appear here.",
            )}
          </p>
        )}
      </section>
    </div>
  );
}
