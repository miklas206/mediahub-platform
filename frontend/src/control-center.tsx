import {
  useEffect,
  useId,
  useState,
  useSyncExternalStore,
  type CSSProperties,
} from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  Clock3,
  Cpu,
  Download,
  Layers3,
  MemoryStick,
  Radio,
  ShieldCheck,
  ShieldAlert,
  Database,
} from "lucide-react";
import { CountryFlag, countryLabel } from "./country-flag";
import { PlexPosters } from "./plex-posters";
import { useIntegrations } from "./integrations";
import { FjordFlixDashboardCard } from "./fjordflix-dashboard";
import { ongoingTorrents } from "./dashboard-torrents";
import { mediaCapacity, type DashboardData } from "./dashboard-data";
import { api } from "./api";
import { serviceSnapshots } from "./service-snapshots";
import type { RuntimeSnapshot } from "./use-service-snapshot";
import { bytes, uptime } from "./format";
import { getLocale, t } from "./i18n";
import { LayoutGroup } from "./page-layout";
import { ServiceIcon } from "./service-icon";
import { appStatusLabel } from "./seedbox-status";
import type { AppInfo, Health, Metrics } from "./contracts";
import type { Runtime } from "./runtime";
import "./control-center.css";

type Report = { report?: Runtime; failed: boolean; stale?: boolean };
export type Reports = Record<string, Report>;

export function useServiceReports(apps?: AppInfo[]) {
  useSyncExternalStore(serviceSnapshots.subscribe, serviceSnapshots.getVersion);
  const ids = (apps || [])
    .filter(
      (a) =>
        /org\.mediahub\.(plex|seedbox|cloudflared)$/.test(a.packageId) &&
        !a.isMock,
    )
    .map((a) => a.id)
    .sort()
    .join(",");
  useEffect(() => {
    const releases = ids
      ? ids.split(",").map((id) =>
          serviceSnapshots.acquire(`runtime:${id}`, 10000, async (signal) => {
            const data = await api<RuntimeSnapshot>(
              `/apps/${encodeURIComponent(id)}/runtime`,
              "GET",
              undefined,
              signal,
            );
            if (!data.report)
              throw new Error("Service temporarily unavailable");
            return data;
          }),
        )
      : [];
    return () => releases.forEach((release) => release());
  }, [ids]);
  return Object.fromEntries(
    (ids ? ids.split(",") : []).map((id) => {
      const snapshot = serviceSnapshots.get<RuntimeSnapshot>(`runtime:${id}`);
      return [
        id,
        {
          report: snapshot.data?.report,
          failed: !!snapshot.error,
          stale:
            snapshot.stale ||
            Date.now() - (snapshot.updatedAt ?? -Infinity) >= 10000,
        },
      ];
    }),
  ) as Reports;
}
function currentReport(entry?: Report) {
  const report = entry?.report;
  return report?.available && (report.cloudflare || report.agentOnline)
    ? report
    : undefined;
}

export function effectiveServiceStatus(
  app: AppInfo,
  entry: Report | undefined,
  live: boolean,
  failed = false,
): Health["status"] {
  if (!live || failed || entry?.failed || entry?.stale) return "unknown";
  if (!entry) return app.health.status;
  const report = currentReport(entry);
  if (!report) return "unknown";
  if (report.health === "critical" || report.health === "offline")
    return "unhealthy";
  return report.health === "healthy" ||
    report.health === "degraded" ||
    report.health === "unhealthy"
    ? report.health
    : "unknown";
}

export function aggregateServiceStatus(
  states: Health["status"][],
): Health["status"] {
  if (states.includes("unhealthy")) return "unhealthy";
  if (states.includes("degraded")) return "degraded";
  return states.length && states.every((status) => status === "healthy")
    ? "healthy"
    : "unknown";
}

function capacityStatus(
  capacity: ReturnType<typeof mediaCapacity>,
): Health["status"] {
  return !capacity
    ? "unknown"
    : capacity.percent >= 95
      ? "unhealthy"
      : capacity.percent >= 80
        ? "degraded"
        : "healthy";
}

export function ControlSummary({
  metrics,
  apps,
  live,
  reports,
  appsError,
  dashboard,
}: {
  metrics: Metrics;
  apps?: AppInfo[];
  live: boolean;
  reports: Reports;
  appsError: boolean;
  dashboard: DashboardData;
}) {
  const capacity =
    !dashboard.storageError && live
      ? mediaCapacity(dashboard.storage)
      : undefined;
  const states = (apps || []).map((a) =>
    effectiveServiceStatus(a, reports[a.id], live, appsError),
  );
  const healthy = states.filter((status) => status === "healthy").length;
  const seedbox = apps?.find((a) => a.packageId === "org.mediahub.seedbox");
  const qbit =
    seedbox && live && !appsError
      ? currentReport(reports[seedbox.id])?.qBittorrent
      : undefined;
  const tiles = [
    {
      key: "services",
      title: "Services online",
      icon: Layers3,
      value: live && apps && !appsError ? `${healthy} / ${apps.length}` : "—",
      detail:
        !live || appsError ? t("Status unavailable") : t("Installed services"),
      to: "/apps",
      status: aggregateServiceStatus(states),
    },
    {
      key: "downloads",
      title: "Active downloads",
      icon: Download,
      value: qbit ? String(qbit.downloading) : "—",
      detail: qbit
        ? `${bytes(qbit.downloadSpeed)}/s`
        : t(seedbox ? "Waiting for service status" : "Seedbox not installed"),
      to: seedbox ? `/apps/${seedbox.id}?section=torrents` : "/store",
      status:
        seedbox && qbit
          ? effectiveServiceStatus(
              seedbox,
              reports[seedbox.id],
              live,
              appsError,
            )
          : "unknown",
    },
    {
      key: "storage",
      title: "Storage used",
      icon: Database,
      value: bytes(capacity?.used),
      detail: t("of {total}", { total: bytes(capacity?.total) }),
      to: "/storage",
      status: capacityStatus(capacity),
    },
    {
      key: "uptime",
      title: "Core uptime",
      icon: Clock3,
      value: uptime(metrics.coreUptimeSeconds),
      detail: live ? t("Live measurements") : t("Last received measurement"),
      to: "/activity",
      status: live ? "healthy" : "unknown",
    },
  ];
  return (
    <LayoutGroup id="control-summary" className="control-summary">
      {tiles.map(({ key, title, icon: Icon, value, detail, to, status }) => (
        <section
          key={key}
          className="summary-tile panel"
          data-layout-title={title}
        >
          <div className="summary-tile-label">
            <span className="control-icon">
              <Icon size={21} />
            </span>
            <span>{t(title)}</span>
            <span
              className={`summary-status status-dot ${status}`}
              aria-hidden="true"
              title={t(appStatusLabel(status))}
            />
          </div>
          <Link to={to} className="summary-tile-link">
            <strong>{value}</strong>
            <span>{detail}</span>
            <span className="sr-only">
              {t(title)} · {t(appStatusLabel(status))}
            </span>
          </Link>
        </section>
      ))}
    </LayoutGroup>
  );
}

export function ControlStatus({
  apps,
  reports,
  live,
  failed,
}: {
  apps?: AppInfo[];
  reports: Reports;
  live: boolean;
  failed: boolean;
}) {
  const states = (apps || []).map((app) =>
    effectiveServiceStatus(app, reports[app.id], live, failed),
  );
  const state = aggregateServiceStatus(states);
  const Icon =
    state === "healthy"
      ? ShieldCheck
      : state === "degraded" || state === "unhealthy"
        ? ShieldAlert
        : Radio;
  return (
    <div className={`control-status ${state}`} role="status">
      <Icon size={18} />
      <span>
        {t(
          state === "healthy"
            ? "All services operational"
            : state === "degraded" || state === "unhealthy"
              ? "Services need attention"
              : !live
                ? "Reconnecting"
                : states.length || failed
                  ? "Status unavailable"
                  : "Waiting for service status",
        )}
      </span>
    </div>
  );
}

function staleServiceLabel(entry?: Report) {
  return entry?.report && entry.stale ? "Stale" : undefined;
}

function StatusBadge({ status, label }: { status: string; label?: string }) {
  return (
    <span
      className={`badge ${status}`}
      title={
        label === "Stale"
          ? t("Last-good observation; waiting for a fresh update.")
          : undefined
      }
    >
      <span aria-hidden="true" />
      {t(label || appStatusLabel(status))}
    </span>
  );
}

export function ServiceOverview({
  apps,
  reports,
  live,
  failed,
  dashboard,
}: {
  apps?: AppInfo[];
  reports: Reports;
  live: boolean;
  failed: boolean;
  dashboard: DashboardData;
}) {
  const { items: integrations } = useIntegrations();
  const fjordflixIntegrations = integrations.filter(
    (row) => row.enabled && row.tokenConfigured && row.snapshot.fjordflix,
  );
  const plex = apps?.find((a) => a.packageId === "org.mediahub.plex");
  const seedbox = apps?.find((a) => a.packageId === "org.mediahub.seedbox");
  const plexReport =
    live && !failed && plex ? currentReport(reports[plex.id])?.plex : undefined;
  const report =
    live && !failed && seedbox ? currentReport(reports[seedbox.id]) : undefined;
  const vpn = report?.vpn;
  const vpnStatus =
    !vpn || (seedbox && reports[seedbox.id]?.stale)
      ? "unknown"
      : vpn.verified
        ? "healthy"
        : "unhealthy";
  const country = vpn?.verified
    ? dashboard.country || vpn.countryCode || ""
    : "";
  const capacity =
    !dashboard.storageError && live
      ? mediaCapacity(dashboard.storage)
      : undefined;
  const storageStatus = capacityStatus(capacity);
  const downloadStatus = seedbox
    ? effectiveServiceStatus(seedbox, reports[seedbox.id], live, failed)
    : "unknown";
  const active = ongoingTorrents(dashboard.torrents || [])
    .filter((item) => item.progress < 1)
    .slice(0, 2);
  const otherApps = (apps || []).filter((a) => a !== plex && a !== seedbox);
  return (
    <>
      <LayoutGroup id="control-services" className="service-overview">
        {fjordflixIntegrations.map((row) => (
          <FjordFlixDashboardCard
            key={`fjordflix-${row.id}`}
            title={`FjordFlix · ${row.name}`}
            row={row}
          />
        ))}
        {plex && (
          <article
            key="plex"
            data-layout-title="Plex"
            className="service-card service-tile plex-service-tile"
          >
            <div className="service-tile-title">
              <ServiceIcon packageId={plex.packageId} size={32} />
              <h3>Plex</h3>
              <StatusBadge
                label={staleServiceLabel(reports[plex.id])}
                status={effectiveServiceStatus(
                  plex,
                  reports[plex.id],
                  live,
                  failed,
                )}
              />
            </div>
            <dl className="service-facts">
              <div>
                <dd>{plexReport?.activeStreams ?? "—"}</dd>
                <dt>{t("Active streams")}</dt>
              </div>
              <div>
                <dd>{plexReport?.libraries?.length ?? "—"}</dd>
                <dt>{t("Libraries")}</dt>
              </div>
            </dl>
            <PlexPosters appId={plex.id} />
            <Link
              className="service-open"
              to={plex.detailPath || `/apps/${plex.id}`}
            >
              {t("Open {name}", { name: "Plex" })}
              <ArrowUpRight size={13} />
            </Link>
          </article>
        )}
        {seedbox && (
          <article
            key="downloads"
            data-layout-title="qBittorrent"
            className="service-card service-tile download-service-tile"
          >
            <div className="service-tile-title">
              <ServiceIcon packageId={seedbox.packageId} size={32} />
              <h3>qBittorrent</h3>
              <StatusBadge
                status={downloadStatus}
                label={
                  staleServiceLabel(reports[seedbox.id]) ||
                  (downloadStatus === "healthy" &&
                  (report?.qBittorrent?.downloading || 0) > 0
                    ? "Downloading"
                    : undefined)
                }
              />
            </div>
            <dl className="service-facts">
              <div>
                <dd>{report?.qBittorrent?.downloading ?? "—"}</dd>
                <dt>{t("Active downloads")}</dt>
              </div>
              <div>
                <dd className="service-speed">
                  {bytes(report?.qBittorrent?.downloadSpeed)}
                  <small>/s</small>
                </dd>
                <dt>{t("Download speed")}</dt>
              </div>
            </dl>
            <div className="service-downloads">
              {active.length > 0 && live && !dashboard.torrentError ? (
                active.map((item) => (
                  <div className="service-download" key={item.hash}>
                    <span
                      className="download-progress-ring"
                      style={
                        {
                          "--progress": `${Math.min(1, Math.max(0, item.progress)) * 100}%`,
                        } as CSSProperties
                      }
                      aria-hidden="true"
                    />
                    <div>
                      <strong title={item.name}>{item.name}</strong>
                      <progress
                        value={item.progress}
                        max={1}
                        aria-label={t("Progress of {title}", {
                          title: item.name,
                        })}
                      />
                      <small>
                        {bytes(item.dlspeed)}/s
                        {item.eta > 0 && item.eta < 8640000
                          ? ` · ${uptime(item.eta)}`
                          : ""}
                      </small>
                    </div>
                    <span className="download-percent">
                      {Math.round(item.progress * 100)}%
                    </span>
                  </div>
                ))
              ) : (
                <p className="muted">
                  {t(
                    !live || dashboard.torrentError
                      ? "Torrent information is unavailable."
                      : dashboard.torrents
                        ? "No active downloads"
                        : "Loading torrents…",
                  )}
                </p>
              )}
            </div>
            <Link
              className="service-open"
              to={`/apps/${seedbox.id}?section=torrents`}
            >
              {t("View torrents")}
              <ArrowUpRight size={13} />
            </Link>
          </article>
        )}
        {seedbox && (
          <article
            key="vpn"
            data-layout-title="VPN"
            className="service-card service-tile vpn-service-tile"
          >
            <div className="service-tile-title">
              <ShieldCheck className="service-line-icon" size={31} />
              <h3>VPN</h3>
              <StatusBadge
                status={vpnStatus}
                label={
                  staleServiceLabel(reports[seedbox.id]) ||
                  (vpnStatus === "healthy"
                    ? "Connected"
                    : vpnStatus === "unknown"
                      ? "Unknown"
                      : "Not verified")
                }
              />
            </div>
            <div className="vpn-country">
              <CountryFlag country={country} decorative />
              <span>
                <strong>{countryLabel(country) || t("Unknown")}</strong>
                <small>{vpn?.protocol || t("Not verified")}</small>
              </span>
            </div>
            <dl className="service-facts">
              <div>
                <dd className="service-fact-text">
                  {vpn?.verified ? vpn.externalIp || "—" : "—"}
                </dd>
                <dt>{t("External IP")}</dt>
              </div>
              <div>
                <dd className="service-fact-text">
                  {report?.portForwarding?.currentPort ?? "—"}
                </dd>
                <dt>{t("Forwarded port")}</dt>
              </div>
            </dl>
            <div className={`vpn-assurance ${vpnStatus}`}>
              <ShieldCheck size={17} />
              <span>
                {t(
                  vpnStatus === "healthy"
                    ? "VPN connection verified"
                    : vpnStatus === "unknown"
                      ? "Waiting for service status"
                      : "VPN is not verified",
                )}
              </span>
            </div>
            <Link
              className="service-open"
              to={`/apps/${seedbox.id}?section=vpn`}
            >
              {t("View VPN")}
              <ArrowUpRight size={13} />
            </Link>
          </article>
        )}
        <article
          key="storage"
          data-layout-title="Storage"
          className="service-card service-tile storage-service-tile"
        >
          <div className="service-tile-title">
            <Database className="service-line-icon" size={31} />
            <h3>{t("Storage")}</h3>
            <StatusBadge status={storageStatus} />
          </div>
          <div className="storage-usage">
            <strong>{bytes(capacity?.used)}</strong>
            <span>{t("Used")}</span>
            <small>{t("of {total}", { total: bytes(capacity?.total) })}</small>
          </div>
          <div
            className={`meter ${storageStatus === "degraded" ? "warning" : storageStatus === "unhealthy" ? "danger" : ""}`}
            role="meter"
            aria-label={t("Storage used")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={capacity ? Math.round(capacity.percent) : undefined}
          >
            <span style={{ width: `${capacity?.percent || 0}%` }} />
          </div>
          <div className="storage-legend">
            <span>
              <i className="used" />
              {t("Used")}
              <strong>
                {capacity ? `${Math.round(capacity.percent)}%` : "—"}
              </strong>
            </span>
            <span>
              <i />
              {t("Free")}
              <strong>{bytes(capacity?.free)}</strong>
            </span>
          </div>
          <Link className="service-open" to="/storage">
            {t("View storage")}
            <ArrowUpRight size={13} />
          </Link>
        </article>
        {!apps?.length && !fjordflixIntegrations.length && (
          <div key="empty" className="service-empty">
            <Layers3 size={24} />
            <h3>{t(apps ? "No apps installed" : "Loading apps…")}</h3>
            <Link className="text-link" to="/store">
              {t("Open App Store →")}
            </Link>
          </div>
        )}
      </LayoutGroup>
      {!!otherApps.length && (
        <div className="service-extras">
          {otherApps.map((app) => (
            <Link key={app.id} to={app.detailPath || `/apps/${app.id}`}>
              <ServiceIcon packageId={app.packageId} size={18} />
              <span>{app.name}</span>
              <StatusBadge
                label={staleServiceLabel(reports[app.id])}
                status={effectiveServiceStatus(
                  app,
                  reports[app.id],
                  live,
                  failed,
                )}
              />
              <ArrowUpRight size={12} />
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

type Sample = {
  at: number;
  cpu: number | null;
  ram: number;
  down: number | null;
  up: number | null;
};
export function useMetricHistory(metrics?: Metrics) {
  const [samples, setSamples] = useState<Sample[]>([]);
  useEffect(() => {
    if (!metrics) return;
    const at = Date.parse(metrics.timestamp);
    if (!Number.isFinite(at)) return;
    setSamples((current) =>
      at <= (current.at(-1)?.at ?? -Infinity)
        ? current
        : [
            ...current.filter((s) => s.at > at - 15 * 60 * 1000),
            {
              at,
              cpu: metrics.cpu.percent,
              ram: metrics.ram.percent,
              down: metrics.network.downloadBytesPerSecond,
              up: metrics.network.uploadBytesPerSecond,
            },
          ].slice(-180),
    );
  }, [metrics]);
  return samples;
}

export function chartPath(
  samples: Sample[],
  key: "cpu" | "ram" | "down" | "up",
  ceiling: number,
) {
  const first = samples[0]?.at || 0;
  const elapsed = (samples.at(-1)?.at || first) - first;
  let connected = false;
  return samples
    .map((s) => {
      const value = s[key];
      if (value == null || !Number.isFinite(value)) {
        connected = false;
        return "";
      }
      const x = elapsed ? ((s.at - first) / elapsed) * 280 + 2 : 2;
      const y = 82 - Math.max(0, Math.min(1, value / ceiling)) * 76;
      const command = `${connected ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
      connected = true;
      return command;
    })
    .join(" ");
}

/** Close each observed line separately so missing samples remain visible gaps. */
export function chartAreaPath(
  samples: Sample[],
  key: "cpu" | "ram" | "down" | "up",
  ceiling: number,
) {
  return (chartPath(samples, key, ceiling).match(/M[^M]+/g) || [])
    .flatMap((segment) => {
      const points = [...segment.matchAll(/[ML]([\d.]+),[\d.]+/g)];
      if (points.length < 2) return [];
      return `${segment.trim()} L${points.at(-1)![1]},82 L${points[0][1]},82 Z`;
    })
    .join(" ");
}

export function ResourceTrends({
  metrics,
  samples,
  live,
}: {
  metrics: Metrics;
  samples: Sample[];
  live: boolean;
}) {
  const gradientId = useId().replace(/:/g, "");
  const [range, setRange] = useState(15);
  const recent = samples.filter(
    (sample) => sample.at >= (samples.at(-1)?.at || 0) - range * 60000,
  );
  const number = (n: number | null) =>
    n == null
      ? "—"
      : `${n.toLocaleString(getLocale(), { maximumFractionDigits: 1 })}%`;
  const plots = [
    {
      key: "cpu" as const,
      title: "Core CPU",
      icon: Cpu,
      value: number(metrics.cpu.percent),
      detail: t("{count} allocated cores", { count: metrics.cpu.cores }),
      ceiling: 100,
    },
    {
      key: "ram" as const,
      title: "Core memory",
      icon: MemoryStick,
      value: number(metrics.ram.percent),
      detail: `${bytes(metrics.ram.usedBytes)} / ${bytes(metrics.ram.totalBytes)}`,
      ceiling: 100,
    },
    {
      key: "down" as const,
      title: "Network",
      icon: Activity,
      value: `${bytes(metrics.network.downloadBytesPerSecond)}/s`,
      detail: `${t("Upload")}: ${bytes(metrics.network.uploadBytesPerSecond)}/s`,
      ceiling:
        Math.max(1, ...recent.flatMap((s) => [s.down || 0, s.up || 0])) * 1.15,
    },
  ];
  return (
    <section className="panel resource-trends">
      <header className="panel-heading">
        <h2>
          <Activity size={18} />
          {t("System resources")}
        </h2>
        <div
          className="resource-range"
          role="group"
          aria-label={t("Chart time range")}
        >
          {[1, 5, 15].map((minutes) => (
            <button
              type="button"
              key={minutes}
              aria-pressed={range === minutes}
              onClick={() => setRange(minutes)}
            >
              {minutes} min
            </button>
          ))}
        </div>
      </header>
      <div className="resource-plot-grid">
        {plots.map(({ key, title, icon: Icon, value, detail, ceiling }) => (
          <div className={`resource-plot resource-${key}`} key={key}>
            <h3>
              <Icon size={17} />
              {t(title)}
            </h3>
            <strong className="resource-value">{value}</strong>
            <p>{detail}</p>
            <div className="resource-chart">
              {recent.length < 2 ? (
                <p className="chart-pending">
                  {t("Collecting live measurements…")}
                </p>
              ) : (
                <svg
                  viewBox="0 0 284 88"
                  role="img"
                  aria-label={t("{name}: live measurements from this session", {
                    name: t(title),
                  })}
                  preserveAspectRatio="none"
                >
                  <defs>
                    <linearGradient
                      id={`${gradientId}-${key}`}
                      x1="0"
                      y1="0"
                      x2="0"
                      y2="1"
                    >
                      <stop
                        offset="0%"
                        stopColor="currentColor"
                        stopOpacity="0.26"
                      />
                      <stop
                        offset="100%"
                        stopColor="currentColor"
                        stopOpacity="0.02"
                      />
                    </linearGradient>
                  </defs>
                  <path
                    d={chartAreaPath(recent, key, ceiling)}
                    className="chart-area"
                    fill={`url(#${gradientId}-${key})`}
                  />
                  {[6, 44, 82].map((y) => (
                    <line
                      key={y}
                      x1="0"
                      x2="284"
                      y1={y}
                      y2={y}
                      className="chart-gridline"
                    />
                  ))}
                  {[2, 72, 142, 212, 282].map((x) => (
                    <line
                      key={`x${x}`}
                      x1={x}
                      x2={x}
                      y1="6"
                      y2="82"
                      className="chart-gridline"
                    />
                  ))}
                  <path
                    d={chartPath(recent, key, ceiling)}
                    className="chart-line"
                  />
                  {key === "down" && (
                    <path
                      d={chartPath(recent, "up", ceiling)}
                      className="chart-line chart-secondary"
                    />
                  )}
                </svg>
              )}
            </div>
            <div className="chart-axis">
              <span>
                {recent[0]
                  ? new Date(recent[0].at).toLocaleTimeString(getLocale(), {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "—"}
              </span>
              {key === "down" ? (
                <span className="chart-legend">
                  <ArrowDown size={11} />
                  {t("Download")}
                  <ArrowUp size={11} />
                  {t("Upload")}
                </span>
              ) : (
                <span>0–100 %</span>
              )}
              <span>{t("Now")}</span>
            </div>
          </div>
        ))}
      </div>
      <p className="resource-scope">
        <span className={`status-dot ${live ? "healthy" : "unknown"}`} />
        {!live && `${t("Connection interrupted")} · `}
        {t(
          "MediaHub Core · Measurements collected while this dashboard is open.",
        )}
      </p>
    </section>
  );
}
