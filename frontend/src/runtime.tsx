import { translateText, getLocale, t } from "./i18n";

import { LayoutGroup } from "./page-layout";
import { runtimeIssues } from "./runtime-issues";
import { seedboxStatus } from "./seedbox-status";
import {
  seedboxSections,
  seedboxSection,
  type SeedboxSection,
} from "./seedbox-sections";
import { PortReachability } from "./port-reachability";
import { useEffect, useState } from "react";
import { api } from "./api";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Cloud, HardDrive, ShieldCheck, Server } from "lucide-react";
import { useLoad, Panel, ErrorBox } from "./phase2";
import { bytes, uptime } from "./format";
import "./runtime.css";
import { SeedboxDaily } from "./seedbox-daily";
import { SeedboxRSSSettings } from "./seedbox-rss-settings";
import { CloudflareSetupManager } from "./cloudflare-setup";
import { CountryFlag, countryLabel } from "./country-flag";
import { PlexPosters } from "./plex-posters";

export type Runtime = {
  operation?: { state: string; message?: string };
  plex?: {
    running: boolean;
    version: string | null;
    startedAt: string | null;
    libraries: { id: string; name: string; type: string; count?: number }[];
    activeStreams: number | null;
    transcodingStreams?: number;
    directStreams?: number;
    memoryBytes: number | null;
    cpuPercent: number | null;
  };
  checks?: { name: string; status: string; message?: string }[];
  health: string;
  available: boolean;
  observedAt?: number;
  cached: boolean;
  agentOnline: boolean;
  dockerHealthy?: boolean;
  portForwarding?: {
    status: string;
    currentPort: number | null;
    lastRenewed: number | null;
    expiresAt: number | null;
    qBittorrentVerified: boolean;
    listenerVerified?: boolean;
    listenerCheckSupported?: boolean;
    lastError?: string | null;
    plexVerified?: boolean;
  };
  control?: {
    desiredRunning: boolean;
    manualIntervention: string[];
    operation: { state: string; action: string | null; message?: string };
    events: {
      timestamp: number;
      type: string;
      severity: string;
      message: string;
    }[];
  };
  vpn?: {
    verified: boolean;
    externalIp: string | null;
    provider: string;
    protocol: string;
    connectedSince: string | null;
    lastVerified: number | null;
    countryCode?: string | null;
  };
  qBittorrent?: {
    oomKilled?: boolean;
    memoryLimitMiB?: number;
    healthy: boolean;
    running: boolean;
    version: string | null;
    apiAuthenticated: boolean;
    bindingVerified: boolean;
    namespaceVerified: boolean;
    downloadSpeed: number;
    uploadSpeed: number;
    torrents: number;
    downloading: number;
    seeding: number;
    paused: number;
    errors: number;
  };
  storage?: {
    mounted: boolean;
    appWritable: boolean | null;
    source: string | null;
    filesystem: string | null;
    totalBytes: number | null;
    usedBytes: number | null;
    freeBytes: number | null;
    verifiedAt: number | null;
  };
  host?: {
    cpuPercent: number | null;
    cpuCores: number | null;
    ramTotalBytes: number | null;
    ramUsedBytes: number | null;
    ramAvailableBytes: number | null;
    uptimeSeconds: number | null;
  };
  deviceChecks?: {
    id: string;
    connected: boolean;
    status: string;
    message: string;
  }[];
  deviceInventory?: {
    stableIdentity: string | null;
    model: string | null;
    sizeBytes: number | null;
    connected: boolean;
    mounted: boolean;
    mounts: { path: string; readOnly: boolean }[];
  }[];
  cloudflare?: {
    configured: boolean;
    status: string;
    checkedAt: number;
    cached?: boolean;
    metricsReachable: boolean;
    connections: number;
    totalRequests?: number;
    requestErrors?: number;
    version?: string | null;
    message: string;
    tunnelName?: string | null;
    routeCount?: number;
    statusUrlConfigured?: boolean;
    tunnels?: {
      id: string;
      name: string;
      setupMode: string;
      originUrl: string | null;
      statusUrlConfigured: boolean;
      routeCount: number;
      routes: string[];
    }[];
    routes: {
      url: string;
      hostname: string;
      reachable: boolean;
      statusCode: number | null;
      latencyMs: number;
      message: string;
    }[];
  };
};
const stamp = (n?: number | null) =>
  n ? new Date(n * 1000).toLocaleString(getLocale()) : t("Not verified");
const size = (n?: number | null) => (n == null ? t("Unavailable") : bytes(n));
const localPlexUrl = () => {
  if (typeof window === "undefined") return "";
  const hostname = window.location.hostname.toLowerCase();
  const isPrivate =
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "::1" ||
    hostname.startsWith("10.") ||
    hostname.startsWith("192.168.") ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(hostname);
  return isPrivate
    ? `http://${window.location.hostname}:32400/web`
    : "https://app.plex.tv/desktop/#!/settings/web/general";
};
function Row({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="runtime-row">
      <dt>{typeof label === "string" ? t(label) : translateText(label)}</dt>
      <dd>{typeof value === "string" ? t(value) : value}</dd>
    </div>
  );
}
function Verified({ value }: { value?: boolean | null }) {
  return (
    <span
      className={`runtime-verdict ${value === true ? "yes" : value === false ? "no" : "unknown"}`}
    >
      {value === true
        ? t("Verified")
        : value === false
          ? t("Not ready")
          : t("Not checked")}
    </span>
  );
}
export function DeviceDiagnostics({ report: r }: { report: Runtime }) {
  return (
    <div className="runtime-device-diagnostics">
      <div className="runtime-device-checks">
        {r.deviceChecks?.map((d) => (
          <div key={d.id}>
            <strong>{d.id}</strong>
            <Verified value={d.connected} />
            <span>{translateText(d.message)}</span>
          </div>
        ))}
      </div>
      <div className="runtime-device-list">
        {r.deviceInventory
          ?.filter((d) => d.stableIdentity)
          .map((d, i) => (
            <article key={d.stableIdentity || i}>
              <strong>{d.model || t("Block device")}</strong>
              <span>
                {size(d.sizeBytes)} ·{" "}
                {d.connected ? t("Present") : t("Missing")} ·{" "}
                {d.mounted ? t("Mounted") : t("Unmounted")}
              </span>
              <code>{d.stableIdentity}</code>
              <span>
                {d.mounts
                  .map(
                    (m) =>
                      `${m.path} (${m.readOnly ? "read-only" : t("read/write mount")})`,
                  )
                  .join(" · ")}
              </span>
            </article>
          ))}
      </div>
      {!r.deviceChecks?.length && !r.deviceInventory?.length && (
        <p>{t("No device diagnostics were reported by this Agent.")}</p>
      )}
      <p className="muted">
        {t(
          "Device and mount flags are separate from the app’s actual write permission.",
        )}
      </p>
    </div>
  );
}
function SeedboxPanel({
  report: r,
  section,
}: {
  report: Runtime;
  section: SeedboxSection;
}) {
  const vpn = r.vpn,
    q = r.qBittorrent,
    disk = r.storage,
    host = r.host;
  const counts = q?.apiAuthenticated ? q : undefined;
  const status = seedboxStatus(r);
  return (
    <div className={`runtime-workspace seedbox-workspace section-${section}`}>
      <header className="runtime-summary">
        <div>
          <p className="eyebrow">{t("INSTALLED APP · SEEDBOX")}</p>
          <h1>{t("Seedbox")}</h1>
        </div>
        <div className={`runtime-health ${r.health}`}>
          <ShieldCheck size={22} />
          {t(status.label)}
        </div>
      </header>
      <div className="runtime-observed">
        <span>
          {t("Last observation: ")}
          {stamp(r.observedAt)}
        </span>
        <span>
          {r.cached ? t("Cached observation") : t("Fresh observation")}
          {t(" · updates every 10s")}
        </span>
      </div>
      {status.message && (
        <div role="status" className="seedbox-status-notice">
          <strong>{t(status.label)}</strong>
          <span>{t(status.message)}</span>
          {r.available && (
            <Link to={{ search: "?section=settings" }}>
              {t("Open runtime controls")}
            </Link>
          )}
        </div>
      )}
      <LayoutGroup id="runtime-SeedboxPanel-1" className="runtime-panels">
        {section === "vpn" && (
          <Panel title={t("VPN protection")}>
            <div className="runtime-panel-title">
              <ShieldCheck />
              <strong>
                {vpn?.verified
                  ? t("Connected · verified")
                  : t("Disconnected / unverified")}
              </strong>
            </div>
            <dl>
              <Row
                label={t("External IP")}
                value={vpn?.externalIp || t("Not verified")}
              />
              <Row
                label={t("Provider")}
                value={vpn?.provider || t("Unavailable")}
              />
              <Row
                label={t("Protocol")}
                value={vpn?.protocol || t("Unavailable")}
              />
              <Row
                label={t("Last verified")}
                value={stamp(vpn?.lastVerified)}
              />
              <Row
                label={t("Container started — not tunnel uptime")}
                value={
                  vpn?.connectedSince
                    ? new Date(vpn.connectedSince).toLocaleString(getLocale())
                    : t("Unavailable")
                }
              />
            </dl>
            <h3>{t("Torrent port forwarding")}</h3>
            {r.portForwarding?.lastError && (
              <p role="alert" className="notice">
                {translateText(r.portForwarding.lastError)}
              </p>
            )}
            <dl>
              <Row
                label={t("Lease status")}
                value={r.portForwarding?.status || t("Not checked")}
              />
              <Row
                label={t("Current port")}
                value={r.portForwarding?.currentPort ?? t("Not assigned")}
              />
              <Row
                label={t("Last renewed")}
                value={stamp(r.portForwarding?.lastRenewed)}
              />
              <Row
                label={t("Lease expires")}
                value={stamp(r.portForwarding?.expiresAt)}
              />
              <div className="runtime-row">
                <dt>{t("qBittorrent port configured")}</dt>
                <dd>
                  <Verified value={r.portForwarding?.qBittorrentVerified} />
                </dd>
              </div>
              <div className="runtime-row">
                <dt>{t("Listening socket on VPN port")}</dt>
                <dd>
                  {r.portForwarding?.listenerVerified
                    ? t("Verified")
                    : r.portForwarding?.listenerCheckSupported
                      ? t("Not listening / not verified")
                      : t("Update Agent to check socket")}
                </dd>
              </div>
            </dl>
            <PortReachability
              address={vpn?.externalIp}
              port={r.portForwarding?.currentPort}
              eligible={
                !!vpn?.verified &&
                r.portForwarding?.status === "healthy" &&
                (r.portForwarding?.expiresAt || 0) > Date.now() / 1000
              }
            />
            <p className="muted">
              {t(
                "Torrent traffic through the VPN only. No router or WebUI port is opened.",
              )}
            </p>
          </Panel>
        )}
        {section === "torrents" && (
          <div
            className="seedbox-client-summary"
            data-layout-title={t("Torrent overview")}
          >
            <div className="seedbox-client-metrics">
              <div>
                <span>
                  {t("qBittorrent ")}
                  {q?.version}
                </span>
                <strong>
                  {q?.running ? t("Running") : t("Stopped / unavailable")}
                </strong>
              </div>
              <div>
                <span>{t("Download")}</span>
                <strong>
                  {size(q?.downloadSpeed)}
                  {t("/s")}
                </strong>
              </div>
              <div>
                <span>{t("Upload")}</span>
                <strong>
                  {size(q?.uploadSpeed)}
                  {t("/s")}
                </strong>
              </div>
              {[
                [t("Total"), counts?.torrents],
                [t("Downloading"), counts?.downloading],
                [t("Seeding"), counts?.seeding],
                [t("Paused"), counts?.paused],
                [t("Errors"), counts?.errors],
              ].map(([label, value]) => (
                <div key={label}>
                  <span>
                    {typeof label === "string"
                      ? t(label)
                      : translateText(label)}
                  </span>
                  <strong>{value ?? "\u2014"}</strong>
                </div>
              ))}
            </div>
            <details>
              <summary>{t("Connection checks")}</summary>
              <dl>
                <div className="runtime-row">
                  <dt>{t("Authenticated API")}</dt>
                  <dd>
                    <Verified value={q?.apiAuthenticated} />
                  </dd>
                </div>
                <div className="runtime-row">
                  <dt>{t("VPN interface binding")}</dt>
                  <dd>
                    <Verified value={q?.bindingVerified} />
                  </dd>
                </div>
                <div className="runtime-row">
                  <dt>{t("Shared VPN namespace")}</dt>
                  <dd>
                    <Verified value={q?.namespaceVerified} />
                  </dd>
                </div>
              </dl>
            </details>
          </div>
        )}
        {section === "settings" && (
          <Panel title={t("Downloads storage")}>
            <div className="runtime-panel-title">
              <HardDrive />
              <strong>
                {disk?.mounted ? t("Mounted") : t("Storage unavailable")}
              </strong>
            </div>
            <dl>
              <Row
                label={t("Filesystem")}
                value={disk?.filesystem || t("Unavailable")}
              />
              <Row
                label={t("Source")}
                value={disk?.source || t("Unavailable")}
              />
              <div className="runtime-row">
                <dt>{t("App UID write/read probe")}</dt>
                <dd>
                  <Verified value={disk?.appWritable} />
                </dd>
              </div>
              <Row
                label={t("Mount observation")}
                value={stamp(disk?.verifiedAt)}
              />
              <Row label={t("Capacity")} value={size(disk?.totalBytes)} />
              <Row label={t("Used")} value={size(disk?.usedBytes)} />
              <Row label={t("Free")} value={size(disk?.freeBytes)} />
            </dl>
            {disk?.totalBytes != null && disk.usedBytes != null && (
              <progress
                aria-label={t("Storage used")}
                max={disk.totalBytes}
                value={disk.usedBytes}
              />
            )}
          </Panel>
        )}
        {section === "settings" && (
          <Panel title={t("Seedbox host")}>
            <div className="runtime-panel-title">
              <Server />
              <strong>
                {r.agentOnline ? t("Agent online") : t("Agent offline")}
              </strong>
            </div>
            <dl>
              <Row
                label={t("Docker")}
                value={r.dockerHealthy ? t("Available") : t("Unavailable")}
              />
              <Row
                label={t("CPU")}
                value={
                  host?.cpuPercent == null
                    ? t("Sampling / unavailable")
                    : `${host.cpuPercent.toLocaleString(getLocale(), { minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: false })}% · ${host.cpuCores} cores`
                }
              />
              <Row label={t("RAM used")} value={size(host?.ramUsedBytes)} />
              <Row
                label={t("RAM available")}
                value={size(host?.ramAvailableBytes)}
              />
              <Row label={t("RAM total")} value={size(host?.ramTotalBytes)} />
              <Row
                label={t("Host uptime")}
                value={
                  host?.uptimeSeconds == null
                    ? t("Unavailable")
                    : uptime(host.uptimeSeconds)
                }
              />
            </dl>
          </Panel>
        )}
        {section === "settings" && (
          <div className="layout-card" data-layout-title={t("RSS settings")}>
            <SeedboxRSSSettings />
          </div>
        )}
      </LayoutGroup>
    </div>
  );
}
function RuntimeIssues({
  report,
  kind,
}: {
  report: Runtime;
  kind: "cloudflare" | "plex";
}) {
  const issues = runtimeIssues(report, kind);
  if (!issues.length) return null;
  return (
    <div role="status" className={`runtime-issues ${report.health}`}>
      <strong>
        {["critical", "unhealthy", "offline"].includes(report.health)
          ? t("Action required")
          : t("Warning")}
        {t(": what needs attention")}
      </strong>
      <ul>
        {issues.map((issue) => (
          <li key={issue}>{t(issue)}</li>
        ))}
      </ul>
    </div>
  );
}
function PlexPanel({ report: r, appId }: { report: Runtime; appId?: string }) {
  const p = r.plex;
  return (
    <LayoutGroup id="runtime-workspace-1" className="runtime-workspace">
      <header className="runtime-summary">
        <div>
          <p className="eyebrow">{t("INSTALLED APP · PLEX")}</p>
          <h1>{t("Your media library")}</h1>
          <p>{t("Managed by the local MediaHub Agent · read-only media")}</p>
        </div>
        <div className={`runtime-health ${r.health}`}>
          {translateText(r.health)}
        </div>
      </header>
      <RuntimeIssues report={r} kind="plex" />
      {appId && (
        <Panel title={t("Recently added media")}>
          <div className="plex-library-preview">
            <PlexPosters appId={appId} />
          </div>
        </Panel>
      )}
      <LayoutGroup id="runtime-extra-1" className="runtime-panels">
        <Panel title={t("Plex server")}>
          <dl>
            <Row
              label={t("State")}
              value={p?.running ? t("Running") : t("Stopped / unavailable")}
            />
            <Row label={t("Version")} value={p?.version || t("Unavailable")} />
            <Row
              label={t("Started")}
              value={
                p?.startedAt
                  ? new Date(p.startedAt).toLocaleString(getLocale())
                  : t("Unavailable")
              }
            />
            <Row
              label={t("Active streams")}
              value={p?.activeStreams ?? t("Unavailable")}
            />
            <Row
              label={t("Direct playback")}
              value={p?.directStreams ?? t("Unavailable")}
            />
            <Row
              label={t("Transcoding")}
              value={p?.transcodingStreams ?? t("Unavailable")}
            />
            <Row label={t("RAM")} value={size(p?.memoryBytes)} />
            <Row
              label={t("CPU")}
              value={
                p?.cpuPercent == null
                  ? t("Sampling / unavailable")
                  : `${p.cpuPercent.toLocaleString(getLocale(), { minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: false })}%`
              }
            />
          </dl>
        </Panel>
        <Panel title={t("Secure remote access")}>
          <div className="runtime-panel-title">
            <ShieldCheck />
            <strong>
              {r.vpn?.verified ? t("Protected by VPN") : t("VPN unavailable")}
            </strong>
          </div>
          <dl>
            <Row
              label={t("Provider")}
              value={r.vpn?.provider || t("Unavailable")}
            />
            <div className="runtime-row">
              <dt>{t("Country")}</dt>
              <dd className="country-label">
                <CountryFlag code={r.vpn?.countryCode} size={24} decorative />
                <span>
                  {r.vpn?.countryCode
                    ? countryLabel(r.vpn.countryCode)
                    : t("Not verified")}
                </span>
              </dd>
            </div>
            <Row
              label={t("External IP")}
              value={r.vpn?.externalIp || t("Not verified")}
            />
            <Row
              label={t("Public Plex port")}
              value={r.portForwarding?.currentPort ?? t("Not assigned")}
            />
            <Row
              label={t("Port lease")}
              value={r.portForwarding?.status || t("Not checked")}
            />
            <Row
              label={t("Last renewed")}
              value={stamp(r.portForwarding?.lastRenewed)}
            />
            <div className="runtime-row">
              <dt>{t("Public Plex port reachable")}</dt>
              <dd>
                <Verified value={r.portForwarding?.plexVerified} />
              </dd>
            </div>
          </dl>
          <p className="muted">
            {t(
              "Internet traffic is fail-closed through the dedicated Plex VPN. Local access remains available through the configured LAN address on port 32400.",
            )}
          </p>
        </Panel>
        <Panel title={t("Libraries and storage")}>
          <p>
            <Verified value={r.storage?.mounted} />
            {t(" Required media mounts")}
          </p>
          {p?.libraries.map((l) => (
            <div className="runtime-row" key={l.id}>
              <strong>{l.name}</strong>
              <span>
                {l.count === undefined
                  ? l.type
                  : t("{value0} items · {value1}", {
                      value0: l.count,
                      value1: l.type,
                    })}
              </span>
            </div>
          ))}
          {!p?.libraries.length && (
            <p>{t("No verified library information available.")}</p>
          )}
          <p className="muted">
            {t(
              "Media files are read-only. Plex configuration and transcode data use separate writable storage.",
            )}
          </p>
        </Panel>
      </LayoutGroup>
    </LayoutGroup>
  );
}
function CloudflaredPanel({ report: r }: { report: Runtime }) {
  const c = r.cloudflare;
  return (
    <LayoutGroup id="runtime-workspace-2" className="runtime-workspace">
      <header className="runtime-summary">
        <div>
          <p className="eyebrow">{t("INSTALLED APP · INFRASTRUCTURE")}</p>
          <h1>{t("Cloudflare Tunnel")}</h1>
          <p>
            {t(
              "Optional domain access · read-only monitoring · no Cloudflare account token",
            )}
          </p>
        </div>
        <div className={`runtime-health ${r.health}`}>
          <Cloud size={22} />
          {translateText(r.health)}
        </div>
      </header>
      <div className="runtime-observed">
        <span>
          {t("Last observation: ")}
          {stamp(c?.checkedAt || r.observedAt)}
        </span>
        <span>
          {c?.cached ? t("Cached observation") : t("Fresh observation")}
          {t(" · updates every 10s")}
        </span>
      </div>
      <RuntimeIssues report={r} kind="cloudflare" />
      <LayoutGroup id="runtime-CloudflaredPanel-1" className="runtime-panels">
        <Panel title={t("Tunnel and connector")}>
          <div className="runtime-panel-title">
            <Cloud />
            <strong>
              {c?.connections
                ? t("Connector online")
                : c?.routes.some((route) => route.reachable)
                  ? t("Route online · metrics unavailable")
                  : t("Disconnected / unavailable")}
            </strong>
          </div>
          <dl>
            <Row
              label={t("Monitored tunnels")}
              value={
                c?.tunnels?.length || (c?.configured ? 1 : t("Not configured"))
              }
            />
            <Row
              label={t("cloudflared version")}
              value={c?.version || t("Not observed")}
            />
            <Row
              label={t("Redundant connector sessions")}
              value={c?.metricsReachable ? c.connections : t("Not observed")}
            />
            <Row
              label={t("Published routes monitored")}
              value={c?.routeCount ?? c?.routes.length ?? 0}
            />
            <Row
              label={t("Metrics helper")}
              value={c?.metricsReachable ? t("Reachable") : t("Unavailable")}
            />
            <Row
              label={t("Requests observed")}
              value={
                c?.metricsReachable
                  ? (c.totalRequests?.toLocaleString(getLocale()) ??
                    t("Unavailable"))
                  : t("Unavailable")
              }
            />
            <Row
              label={t("Errors observed")}
              value={
                c?.metricsReachable
                  ? (c.requestErrors?.toLocaleString(getLocale()) ??
                    t("Unavailable"))
                  : t("Unavailable")
              }
            />
          </dl>
        </Panel>
        <Panel title={t("Published routes")}>
          {c?.routes.length ? (
            <dl>
              {c.routes.map((route) => (
                <div className="runtime-row" key={route.url}>
                  <dt>
                    <strong>{route.hostname}</strong>
                    <small>{translateText(route.message)}</small>
                  </dt>
                  <dd>
                    <Verified value={route.reachable} />
                    <small>
                      {route.statusCode || t("No response")} · {route.latencyMs}
                      {t(" ms")}
                    </small>
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p>{t("No public route probes are configured.")}</p>
          )}
          <p className="muted">
            {t(
              "A login response or redirect still proves that Cloudflare can reach the origin. Server errors and connection failures are reported as unavailable.",
            )}
          </p>
        </Panel>
      </LayoutGroup>
      <Panel title={t("Security model")}>
        <div className="runtime-panel-title">
          <ShieldCheck />
          <strong>{t("Least-privilege monitoring")}</strong>
        </div>
        <p>
          {t(
            "MediaHub receives only a sanitized local status document. Tunnel tokens, Cloudflare API keys, DNS changes and public route configuration stay outside MediaHub.",
          )}
        </p>
        <p className="muted">
          {t(
            "Release checks read only Cloudflare’s official public release metadata. Updates remain manual because the correct procedure depends on whether cloudflared was installed with Docker, a package manager or a standalone binary.",
          )}
        </p>
      </Panel>
    </LayoutGroup>
  );
}
const views: Record<string, typeof PlexPanel> = {
  plex: PlexPanel,
  cloudflare: CloudflaredPanel,
};
export function RemoteRuntimeLogs({ appId }: { appId: string }) {
  const { data, error, reload } = useLoad<{
    entries: {
      timestamp: number;
      hostId: string;
      app: string;
      type: string;
      severity: string;
      message: string;
    }[];
  }>(`/apps/${appId}/logs`);
  const [component, setComponent] = useState("all"),
    [severity, setSeverity] = useState("all");
  const components = [
    "all",
    ...new Set([
      ...(data?.entries.map((e) => e.type.split(".")[0]) || []),
      "recovery",
    ]),
  ];
  return (
    <Panel title={t("Agent runtime diagnostics")}>
      <ErrorBox error={error} />
      <div className="runtime-toolbar">
        <label>
          {t("Component")}{" "}
          <select
            value={component}
            onChange={(e) => setComponent(e.target.value)}
          >
            {components.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          {t("Severity")}{" "}
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
          >
            {["all", "info", "warning", "error"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <button onClick={reload}>{t("Refresh logs")}</button>
      </div>
      <p className="muted">
        {t(
          "Structured diagnostics only. Raw process output, credentials and cookies are not forwarded.",
        )}
      </p>
      <div style={{ maxHeight: "32rem", overflow: "auto" }}>
        {data?.entries
          .filter(
            (e) =>
              (severity === "all" || e.severity === severity) &&
              (component === "all" ||
                e.type.startsWith(component + ".") ||
                (component === "recovery" && e.type.includes("recovery"))),
          )
          .slice()
          .reverse()
          .map((e, i) => (
            <p key={i}>
              {stamp(e.timestamp)} · {translateText(e.severity)} ·{" "}
              {translateText(e.message)}
              <small>
                {" "}
                · {e.app} / {e.hostId}
              </small>
            </p>
          ))}
      </div>
    </Panel>
  );
}
export function AppRuntimePage() {
  const { appId } = useParams();
  const [searchParams] = useSearchParams();
  const section = seedboxSection(searchParams.get("section"));
  const { data, error, reload } = useLoad<{
    view: string;
    report: Runtime;
    operatorUrl?: string;
  }>(`/apps/${appId}/runtime`);
  useEffect(() => {
    const timer = setInterval(reload, 10000);
    return () => clearInterval(timer);
  }, [reload]);
  const View = data && views[data.view];
  const [busy, setBusy] = useState(false),
    [actionError, setActionError] = useState("");
  const [updateResult, setUpdateResult] = useState(""),
    [releaseUrl, setReleaseUrl] = useState("");
  const [showLogs, setShowLogs] = useState(false),
    [component, setComponent] = useState("all");
  useEffect(() => {
    setActionError("");
    setUpdateResult("");
    setReleaseUrl("");
    setShowLogs(false);
    setComponent("all");
  }, [appId]);
  const act = async (action: string) => {
    if (
      action !== "test-vpn" &&
      !window.confirm(
        `${action}: this can interrupt ${data?.view === "plex" ? t("Plex playback") : t("Seedbox transfers")}. Continue?`,
      )
    )
      return;
    setBusy(true);
    setActionError("");
    try {
      await api(`/apps/${appId}/actions/${action}`, "POST");
      reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };
  const control = data?.report.control;
  const operatorUrl =
    data?.operatorUrl || (data?.view === "plex" ? localPlexUrl() : "");
  const checkUpdate = async () => {
    setBusy(true);
    setActionError("");
    setUpdateResult("");
    try {
      const result = await api<{
        message?: string;
        reason?: string;
        releaseVersions?: string[];
        installedVersion?: string | null;
        latestVersion?: string | null;
        releaseUrl?: string | null;
      }>(`/apps/${appId}/update-check`, "POST");
      const versions = result.latestVersion
        ? `Installed ${result.installedVersion || "not observed"} · Latest ${result.latestVersion}`
        : "";
      setUpdateResult(
        [
          result.message || result.reason || "Update check completed",
          versions,
          ...(result.releaseVersions || []),
        ]
          .filter(Boolean)
          .join(" · "),
      );
      setReleaseUrl(result.releaseUrl || "");
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Update check failed");
    } finally {
      setBusy(false);
    }
  };
  const plexUpdate = async (rollback = false) => {
    if (
      !window.confirm(
        rollback
          ? t(
              "Restore the previous Plex version and database? Media files are not changed.",
            )
          : t(
              "Update Plex? Active playback will stop. A configuration rollback snapshot is saved first.",
            ),
      )
    )
      return;
    setBusy(true);
    setActionError("");
    try {
      const response = await api<{ message: string }>(
        rollback ? "/plex/rollback" : "/plex/update",
        "POST",
      );
      setUpdateResult(response.message);
      reload();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <LayoutGroup id="runtime-AppRuntimePage-1" className="stack">
      <div className="runtime-toolbar">
        <Link to="/apps">{t("← All apps")}</Link>
        <button onClick={reload}>{t("Refresh status")}</button>
        {data?.view === "seedbox" && (
          <Link to={`/apps/${appId}/install`}>{t("Review installation")}</Link>
        )}
      </div>
      <ErrorBox error={error} />
      {data?.view === "seedbox" && (
        <nav className="seedbox-sections" aria-label={t("Seedbox sections")}>
          {seedboxSections.map(([key, label]) => (
            <Link
              key={key}
              to={{
                search: (() => {
                  const next = new URLSearchParams(searchParams);
                  next.set("section", key);
                  return next.toString();
                })(),
              }}
              className={section === key ? "selected" : ""}
              aria-current={section === key ? "page" : undefined}
            >
              {typeof label === "string" ? t(label) : translateText(label)}
            </Link>
          ))}
        </nav>
      )}
      {data?.view === "seedbox" ? (
        <SeedboxPanel
          section={section}
          report={
            error
              ? {
                  health: "offline",
                  available: false,
                  agentOnline: false,
                  cached: false,
                }
              : data.report
          }
        />
      ) : View && data ? (
        <View
          appId={appId}
          report={
            error
              ? {
                  health: "offline",
                  available: false,
                  agentOnline: false,
                  cached: false,
                }
              : data.report
          }
        />
      ) : (
        <p role="status">{t("Loading app status…")}</p>
      )}
      {data?.view === "cloudflare" && (
        <CloudflareSetupManager onSaved={reload} />
      )}
      {data?.view === "seedbox" && section !== "settings" && (
        <SeedboxDaily
          section={section}
          externalIp={data.report.vpn?.externalIp}
          forwarding={data.report.portForwarding?.status}
        />
      )}
      {data?.view === "cloudflare" && (
        <Panel title={t("Updates and safety")}>
          <p>
            {t(
              "MediaHub can check Cloudflare’s official stable release without receiving access to your Cloudflare account.",
            )}
          </p>
          <div className="runtime-toolbar">
            <button disabled={busy} onClick={checkUpdate}>
              {busy ? t("Checking…") : t("Check official release")}
            </button>
            {releaseUrl && (
              <a href={releaseUrl} target="_blank" rel="noreferrer">
                {t("View official release →")}
              </a>
            )}
          </div>
          <p role="status">
            {translateText(updateResult) ||
              t("No release check has been run in this session.")}
          </p>
          {actionError && <div role="alert">{actionError}</div>}
          <p className="muted">
            {t(
              "No automatic update or restart is performed. That avoids choosing the wrong installation method and unexpectedly interrupting the tunnel.",
            )}
          </p>
        </Panel>
      )}
      {data &&
        data.view !== "cloudflare" &&
        (data.view !== "seedbox" || section === "settings") && (
          <Panel title={t("Runtime controls")}>
            <p>
              {t(
                "Actions use the paired Agent. Starting revalidates the required storage and app safety checks.",
              )}
            </p>
            <div className="runtime-toolbar">
              {(data.view === "plex"
                ? [
                    ["start", t("Start Plex")],
                    ["stop", t("Stop Plex")],
                    ["restart", t("Restart Plex")],
                  ]
                : [
                    ["start", t("Start Seedbox")],
                    ["stop", t("Stop Seedbox")],
                    ["restart", t("Restart Seedbox")],
                    ["restart-vpn", t("Restart VPN")],
                    ["restart-qbittorrent", t("Restart qBittorrent")],
                    ["test-vpn", t("Test VPN")],
                  ]
              ).map(([action, label]) => (
                <button
                  key={action}
                  disabled={
                    busy ||
                    !!error ||
                    !data.report.available ||
                    control?.operation.state === "running"
                  }
                  onClick={() => act(action)}
                >
                  {typeof label === "string" ? t(label) : translateText(label)}
                </button>
              ))}
            </div>
            {actionError && <div role="alert">{actionError}</div>}
            {data.view === "plex" && (
              <>
                <div className="runtime-toolbar">
                  <a className="runtime-primary-link" href={operatorUrl}>
                    {t("Open Plex settings")}
                  </a>
                  <button
                    disabled={busy || !!error || !data.report.available}
                    onClick={checkUpdate}
                  >
                    {t("Check for updates")}
                  </button>
                  <button
                    disabled={
                      busy ||
                      data.report.operation?.state === "running" ||
                      !!error ||
                      !data.report.available
                    }
                    onClick={() => plexUpdate()}
                  >
                    {t("Update Plex")}
                  </button>
                  {data.report.operation?.state === "failed" && (
                    <button disabled={busy} onClick={() => plexUpdate(true)}>
                      {t("Restore previous version")}
                    </button>
                  )}
                </div>
                <p role="status">
                  {translateText(data.report.operation?.message) ||
                    translateText(updateResult)}
                </p>
              </>
            )}
            <p role="status">
              {control?.operation.action || t("No operation")}:{" "}
              {translateText(control?.operation.state) || t("idle")}{" "}
              {translateText(control?.operation.message)}
            </p>
            {!!control?.manualIntervention.length && (
              <div role="alert">
                {t("Manual intervention required:")}{" "}
                {control.manualIntervention.join(", ")}
                {t(". Automatic retries are stopped.")}
              </div>
            )}
            <button onClick={() => setShowLogs(!showLogs)}>
              {showLogs ? t("Hide logs") : t("View logs")}
            </button>
            {operatorUrl && data.view !== "plex" && (
              <p>
                <a href={operatorUrl} rel="noreferrer">
                  {data.view === "plex"
                    ? t("Open Plex")
                    : t("Open qBittorrent")}
                </a>
                {data.view === "seedbox" &&
                  t(
                    " · Requires the SSH tunnel on this Windows PC. Existing qBittorrent login remains enabled.",
                  )}
              </p>
            )}
            {showLogs && data.view === "plex" && appId && (
              <RemoteRuntimeLogs appId={appId} />
            )}
            {showLogs && data.view === "seedbox" && (
              <>
                <label>
                  {t("Component")}{" "}
                  <select
                    value={component}
                    onChange={(e) => setComponent(e.target.value)}
                  >
                    {[
                      "all",
                      "seedbox",
                      "vpn",
                      "qbittorrent",
                      "storage",
                      "recovery",
                    ].map((c) => (
                      <option key={c} value={c}>
                        {c === "seedbox" ? t("Seedbox Agent") : c}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="muted">
                  {t(
                    "Safe, structured Agent diagnostics. Raw container output and credentials are never forwarded.",
                  )}
                </p>
                {control?.events
                  .filter(
                    (e) =>
                      component === "all" ||
                      e.type.startsWith(component + ".") ||
                      (component === "recovery" && e.type.includes("recovery")),
                  )
                  .slice()
                  .reverse()
                  .map((e, i) => (
                    <p key={i}>
                      {stamp(e.timestamp)} · {translateText(e.severity)} ·{" "}
                      {translateText(e.message)}
                    </p>
                  ))}
              </>
            )}
          </Panel>
        )}
    </LayoutGroup>
  );
}
