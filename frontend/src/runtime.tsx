import { useEffect, useState } from "react";
import { api } from "./api";
import { Link, useParams } from "react-router-dom";
import { Activity, Cloud, HardDrive, ShieldCheck, Server } from "lucide-react";
import { useLoad, Panel, ErrorBox } from "./phase2";
import { bytes, uptime } from "./format";
import "./runtime.css";
import { SeedboxDaily } from "./seedbox-daily";
import { CloudflareSetupManager } from "./cloudflare-setup";

type Runtime = {
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
  n ? new Date(n * 1000).toLocaleString() : "Not verified";
const size = (n?: number | null) => (n == null ? "Unavailable" : bytes(n));
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
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
function Verified({ value }: { value?: boolean | null }) {
  return (
    <span
      className={`runtime-verdict ${value === true ? "yes" : value === false ? "no" : "unknown"}`}
    >
      {value === true
        ? "Verified"
        : value === false
          ? "Not ready"
          : "Not checked"}
    </span>
  );
}
function SeedboxPanel({ report: r }: { report: Runtime }) {
  const vpn = r.vpn,
    q = r.qBittorrent,
    disk = r.storage,
    host = r.host;
  const counts = q?.apiAuthenticated ? q : undefined;
  return (
    <div className="runtime-workspace">
      <header className="runtime-summary">
        <div>
          <p className="eyebrow">INSTALLED APP · SEEDBOX</p>
          <h1>Protected downloads</h1>
          <p>MediaHub Core → paired Agent → isolated runtime</p>
        </div>
        <div className={`runtime-health ${r.health}`}>
          <ShieldCheck size={22} />
          {r.health}
        </div>
      </header>
      <div className="runtime-observed">
        <span>Last observation: {stamp(r.observedAt)}</span>
        <span>
          {r.cached ? "Cached observation" : "Fresh observation"} · updates
          every 10s
        </span>
      </div>
      {!r.available && (
        <div role="alert" className="notice">
          Agent offline or status unavailable. Previous values are not treated
          as healthy.
        </div>
      )}
      <div className="runtime-panels">
        <Panel title="VPN protection">
          <div className="runtime-panel-title">
            <ShieldCheck />
            <strong>
              {vpn?.verified
                ? "Connected · verified"
                : "Disconnected / unverified"}
            </strong>
          </div>
          <dl>
            <Row
              label="External IP"
              value={vpn?.externalIp || "Not verified"}
            />
            <Row label="Provider" value={vpn?.provider || "Unavailable"} />
            <Row label="Protocol" value={vpn?.protocol || "Unavailable"} />
            <Row label="Last verified" value={stamp(vpn?.lastVerified)} />
            <Row
              label="Container started — not tunnel uptime"
              value={
                vpn?.connectedSince
                  ? new Date(vpn.connectedSince).toLocaleString()
                  : "Unavailable"
              }
            />
          </dl>
          <h3>Torrent port forwarding</h3>
          <dl>
            <Row
              label="Lease status"
              value={r.portForwarding?.status || "Not checked"}
            />
            <Row
              label="Current port"
              value={r.portForwarding?.currentPort ?? "Not assigned"}
            />
            <Row
              label="Last renewed"
              value={stamp(r.portForwarding?.lastRenewed)}
            />
            <Row
              label="Lease expires"
              value={stamp(r.portForwarding?.expiresAt)}
            />
            <div className="runtime-row">
              <dt>qBittorrent port verified</dt>
              <dd>
                <Verified value={r.portForwarding?.qBittorrentVerified} />
              </dd>
            </div>
          </dl>
          <p className="muted">
            Torrent traffic through the VPN only. No router or WebUI port is
            opened.
          </p>
        </Panel>
        <Panel title="qBittorrent">
          <div className="runtime-panel-title">
            <Activity />
            <strong>{q?.running ? "Running" : "Stopped / unavailable"}</strong>
            <span>{q?.version}</span>
          </div>
          <div className="runtime-speeds">
            <div>
              <span>Download</span>
              <strong>{size(q?.downloadSpeed)}/s</strong>
            </div>
            <div>
              <span>Upload</span>
              <strong>{size(q?.uploadSpeed)}/s</strong>
            </div>
          </div>
          <dl>
            <div className="runtime-row">
              <dt>Authenticated API</dt>
              <dd>
                <Verified value={q?.apiAuthenticated} />
              </dd>
            </div>
            <div className="runtime-row">
              <dt>VPN interface binding</dt>
              <dd>
                <Verified value={q?.bindingVerified} />
              </dd>
            </div>
            <div className="runtime-row">
              <dt>Shared VPN namespace</dt>
              <dd>
                <Verified value={q?.namespaceVerified} />
              </dd>
            </div>
          </dl>
          <div className="runtime-counts">
            {[
              ["Total", counts?.torrents],
              ["Downloading", counts?.downloading],
              ["Seeding", counts?.seeding],
              ["Paused", counts?.paused],
              ["Errors", counts?.errors],
            ].map(([label, value]) => (
              <div key={label}>
                <strong>{value ?? "—"}</strong>
                <span>{label}</span>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Downloads storage">
          <div className="runtime-panel-title">
            <HardDrive />
            <strong>{disk?.mounted ? "Mounted" : "Storage unavailable"}</strong>
          </div>
          <dl>
            <Row label="Filesystem" value={disk?.filesystem || "Unavailable"} />
            <Row label="Source" value={disk?.source || "Unavailable"} />
            <div className="runtime-row">
              <dt>App UID write/read probe</dt>
              <dd>
                <Verified value={disk?.appWritable} />
              </dd>
            </div>
            <Row label="Mount observation" value={stamp(disk?.verifiedAt)} />
            <Row label="Capacity" value={size(disk?.totalBytes)} />
            <Row label="Used" value={size(disk?.usedBytes)} />
            <Row label="Free" value={size(disk?.freeBytes)} />
          </dl>
          {disk?.totalBytes != null && disk.usedBytes != null && (
            <progress
              aria-label="Storage used"
              max={disk.totalBytes}
              value={disk.usedBytes}
            />
          )}
        </Panel>
        <Panel title="Seedbox host">
          <div className="runtime-panel-title">
            <Server />
            <strong>{r.agentOnline ? "Agent online" : "Agent offline"}</strong>
          </div>
          <dl>
            <Row
              label="Docker"
              value={r.dockerHealthy ? "Available" : "Unavailable"}
            />
            <Row
              label="CPU"
              value={
                host?.cpuPercent == null
                  ? "Sampling / unavailable"
                  : `${host.cpuPercent.toFixed(1)}% · ${host.cpuCores} cores`
              }
            />
            <Row label="RAM used" value={size(host?.ramUsedBytes)} />
            <Row label="RAM available" value={size(host?.ramAvailableBytes)} />
            <Row label="RAM total" value={size(host?.ramTotalBytes)} />
            <Row
              label="Host uptime"
              value={
                host?.uptimeSeconds == null
                  ? "Unavailable"
                  : uptime(host.uptimeSeconds)
              }
            />
          </dl>
        </Panel>
      </div>
      <Panel title="Device requirements">
        <div className="runtime-device-checks">
          {r.deviceChecks?.map((d) => (
            <div key={d.id}>
              <strong>{d.id}</strong>
              <Verified value={d.connected} />
              <span>{d.message}</span>
            </div>
          ))}
        </div>
        <div className="runtime-device-list">
          {r.deviceInventory
            ?.filter((d) => d.stableIdentity)
            .map((d, i) => (
              <article key={d.stableIdentity || i}>
                <strong>{d.model || "Block device"}</strong>
                <span>
                  {size(d.sizeBytes)} · {d.connected ? "Present" : "Missing"} ·{" "}
                  {d.mounted ? "Mounted" : "Unmounted"}
                </span>
                <code>{d.stableIdentity}</code>
                <span>
                  {d.mounts
                    .map(
                      (m) =>
                        `${m.path} (${m.readOnly ? "read-only" : "read/write mount"})`,
                    )
                    .join(" · ")}
                </span>
              </article>
            ))}
        </div>
        <p className="muted">
          Device and mount flags are separate from the app’s actual write
          permission.
        </p>
      </Panel>
    </div>
  );
}
function PlexPanel({ report: r }: { report: Runtime }) {
  const p = r.plex;
  return (
    <div className="runtime-workspace">
      <header className="runtime-summary">
        <div>
          <p className="eyebrow">INSTALLED APP · PLEX</p>
          <h1>Your media library</h1>
          <p>Managed by the local MediaHub Agent · read-only media</p>
        </div>
        <div className={`runtime-health ${r.health}`}>{r.health}</div>
      </header>
      <div className="runtime-grid">
        <Panel title="Plex server">
          <dl>
            <Row
              label="State"
              value={p?.running ? "Running" : "Stopped / unavailable"}
            />
            <Row label="Version" value={p?.version || "Unavailable"} />
            <Row
              label="Started"
              value={
                p?.startedAt
                  ? new Date(p.startedAt).toLocaleString()
                  : "Unavailable"
              }
            />
            <Row
              label="Active streams"
              value={p?.activeStreams ?? "Unavailable"}
            />
            <Row
              label="Direct playback"
              value={p?.directStreams ?? "Unavailable"}
            />
            <Row
              label="Transcoding"
              value={p?.transcodingStreams ?? "Unavailable"}
            />
            <Row label="RAM" value={size(p?.memoryBytes)} />
            <Row
              label="CPU"
              value={
                p?.cpuPercent == null
                  ? "Sampling / unavailable"
                  : `${p.cpuPercent.toFixed(1)}%`
              }
            />
          </dl>
        </Panel>
        <Panel title="Secure remote access">
          <div className="runtime-panel-title">
            <ShieldCheck />
            <strong>
              {r.vpn?.verified ? "Protected by VPN" : "VPN unavailable"}
            </strong>
          </div>
          <dl>
            <Row label="Provider" value={r.vpn?.provider || "Unavailable"} />
            <Row label="Country" value={r.vpn?.countryCode || "Not verified"} />
            <Row
              label="External IP"
              value={r.vpn?.externalIp || "Not verified"}
            />
            <Row
              label="Public Plex port"
              value={r.portForwarding?.currentPort ?? "Not assigned"}
            />
            <Row
              label="Port lease"
              value={r.portForwarding?.status || "Not checked"}
            />
            <Row
              label="Last renewed"
              value={stamp(r.portForwarding?.lastRenewed)}
            />
            <div className="runtime-row">
              <dt>Public Plex port reachable</dt>
              <dd>
                <Verified value={r.portForwarding?.plexVerified} />
              </dd>
            </div>
          </dl>
          <p className="muted">
            Internet traffic is fail-closed through the dedicated Plex VPN.
            Local access remains available through the configured LAN address on
            port 32400.
          </p>
        </Panel>
        <Panel title="Libraries and storage">
          <p>
            <Verified value={r.storage?.mounted} /> Required media mounts
          </p>
          {p?.libraries.map((l) => (
            <div className="runtime-row" key={l.id}>
              <strong>{l.name}</strong>
              <span>
                {l.count === undefined
                  ? l.type
                  : `${l.count} items · ${l.type}`}
              </span>
            </div>
          ))}
          {!p?.libraries.length && (
            <p>No verified library information available.</p>
          )}
          <p className="muted">
            Media files are read-only. Plex configuration and transcode data use
            separate writable storage.
          </p>
        </Panel>
      </div>
    </div>
  );
}
function CloudflaredPanel({ report: r }: { report: Runtime }) {
  const c = r.cloudflare;
  return (
    <div className="runtime-workspace">
      <header className="runtime-summary">
        <div>
          <p className="eyebrow">INSTALLED APP · INFRASTRUCTURE</p>
          <h1>Cloudflare Tunnel</h1>
          <p>
            Optional domain access · read-only monitoring · no Cloudflare
            account token
          </p>
        </div>
        <div className={`runtime-health ${r.health}`}>
          <Cloud size={22} />
          {r.health}
        </div>
      </header>
      <div className="runtime-observed">
        <span>Last observation: {stamp(c?.checkedAt || r.observedAt)}</span>
        <span>
          {c?.cached ? "Cached observation" : "Fresh observation"} · updates
          every 10s
        </span>
      </div>
      {!c?.configured && (
        <div role="alert" className="notice">
          Cloudflare Tunnel monitoring is not configured for this installation.
        </div>
      )}
      <div className="runtime-panels">
        <Panel title="Tunnel and connector">
          <div className="runtime-panel-title">
            <Cloud />
            <strong>
              {c?.connections
                ? "Connector online"
                : c?.routes.some((route) => route.reachable)
                  ? "Route online · metrics unavailable"
                  : "Disconnected / unavailable"}
            </strong>
          </div>
          <dl>
            <Row
              label="Monitored tunnels"
              value={
                c?.tunnels?.length || (c?.configured ? 1 : "Not configured")
              }
            />
            <Row
              label="cloudflared version"
              value={c?.version || "Not observed"}
            />
            <Row
              label="Redundant connector sessions"
              value={c?.metricsReachable ? c.connections : "Not observed"}
            />
            <Row
              label="Published routes monitored"
              value={c?.routeCount ?? c?.routes.length ?? 0}
            />
            <Row
              label="Metrics helper"
              value={c?.metricsReachable ? "Reachable" : "Unavailable"}
            />
            <Row
              label="Requests observed"
              value={c?.totalRequests?.toLocaleString() ?? "Unavailable"}
            />
            <Row
              label="Errors observed"
              value={c?.requestErrors?.toLocaleString() ?? "Unavailable"}
            />
          </dl>
        </Panel>
        <Panel title="Published routes">
          {c?.routes.length ? (
            <dl>
              {c.routes.map((route) => (
                <div className="runtime-row" key={route.url}>
                  <dt>
                    <strong>{route.hostname}</strong>
                    <small>{route.message}</small>
                  </dt>
                  <dd>
                    <Verified value={route.reachable} />
                    <small>
                      {route.statusCode || "No response"} · {route.latencyMs} ms
                    </small>
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p>No public route probes are configured.</p>
          )}
          <p className="muted">
            A login response or redirect still proves that Cloudflare can reach
            the origin. Server errors and connection failures are reported as
            unavailable.
          </p>
        </Panel>
      </div>
      <Panel title="Security model">
        <div className="runtime-panel-title">
          <ShieldCheck />
          <strong>Least-privilege monitoring</strong>
        </div>
        <p>
          MediaHub receives only a sanitized local status document. Tunnel
          tokens, Cloudflare API keys, DNS changes and public route
          configuration stay outside MediaHub.
        </p>
        <p className="muted">
          Release checks read only Cloudflare’s official public release
          metadata. Updates remain manual because the correct procedure depends
          on whether cloudflared was installed with Docker, a package manager or
          a standalone binary.
        </p>
      </Panel>
    </div>
  );
}
const views: Record<string, typeof SeedboxPanel> = {
  seedbox: SeedboxPanel,
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
    <Panel title="Agent runtime diagnostics">
      <ErrorBox error={error} />
      <div className="runtime-toolbar">
        <label>
          Component{" "}
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
          Severity{" "}
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
          >
            {["all", "info", "warning", "error"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <button onClick={reload}>Refresh logs</button>
      </div>
      <p className="muted">
        Structured diagnostics only. Raw process output, credentials and cookies
        are not forwarded.
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
              {stamp(e.timestamp)} · {e.severity} · {e.message}
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
        `${action}: this can interrupt ${data?.view === "plex" ? "Plex playback" : "Seedbox transfers"}. Continue?`,
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
          ? "Restore the previous Plex version and database? Media files are not changed."
          : "Update Plex? Active playback will stop. A configuration rollback snapshot is saved first.",
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
    <div className="stack">
      <div className="runtime-toolbar">
        <Link to="/apps">← All apps</Link>
        <button onClick={reload}>Refresh status</button>
        {data?.view === "seedbox" && (
          <Link to={`/apps/${appId}/install`}>Review installation</Link>
        )}
      </div>
      <ErrorBox error={error} />
      {View && data ? (
        <View
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
        <p role="status">Loading app status…</p>
      )}
      {data?.view === "cloudflare" && (
        <CloudflareSetupManager onSaved={reload} />
      )}
      {data?.view === "seedbox" && (
        <SeedboxDaily
          externalIp={data.report.vpn?.externalIp}
          forwarding={data.report.portForwarding?.status}
        />
      )}
      {data?.view === "cloudflare" && (
        <Panel title="Updates and safety">
          <p>
            MediaHub can check Cloudflare’s official stable release without
            receiving access to your Cloudflare account.
          </p>
          <div className="runtime-toolbar">
            <button disabled={busy} onClick={checkUpdate}>
              {busy ? "Checking…" : "Check official release"}
            </button>
            {releaseUrl && (
              <a href={releaseUrl} target="_blank" rel="noreferrer">
                View official release →
              </a>
            )}
          </div>
          <p role="status">
            {updateResult || "No release check has been run in this session."}
          </p>
          {actionError && <div role="alert">{actionError}</div>}
          <p className="muted">
            No automatic update or restart is performed. That avoids choosing
            the wrong installation method and unexpectedly interrupting the
            tunnel.
          </p>
        </Panel>
      )}
      {data && data.view !== "cloudflare" && (
        <Panel title="Runtime controls">
          <p>
            Actions use the paired Agent. Starting revalidates the required
            storage and app safety checks.
          </p>
          <div className="runtime-toolbar">
            {(data.view === "plex"
              ? [
                  ["start", "Start Plex"],
                  ["stop", "Stop Plex"],
                  ["restart", "Restart Plex"],
                ]
              : [
                  ["start", "Start Seedbox"],
                  ["stop", "Stop Seedbox"],
                  ["restart", "Restart Seedbox"],
                  ["restart-vpn", "Restart VPN"],
                  ["restart-qbittorrent", "Restart qBittorrent"],
                  ["test-vpn", "Test VPN"],
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
                {label}
              </button>
            ))}
          </div>
          {actionError && <div role="alert">{actionError}</div>}
          {data.view === "plex" && (
            <>
              <div className="runtime-toolbar">
                <a className="runtime-primary-link" href={operatorUrl}>
                  Open Plex settings
                </a>
                <button
                  disabled={busy || !!error || !data.report.available}
                  onClick={checkUpdate}
                >
                  Check for updates
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
                  Update Plex
                </button>
                {data.report.operation?.state === "failed" && (
                  <button disabled={busy} onClick={() => plexUpdate(true)}>
                    Restore previous version
                  </button>
                )}
              </div>
              <p role="status">
                {data.report.operation?.message || updateResult}
              </p>
            </>
          )}
          <p role="status">
            {control?.operation.action || "No operation"}:{" "}
            {control?.operation.state || "idle"} {control?.operation.message}
          </p>
          {!!control?.manualIntervention.length && (
            <div role="alert">
              Manual intervention required:{" "}
              {control.manualIntervention.join(", ")}. Automatic retries are
              stopped.
            </div>
          )}
          <button onClick={() => setShowLogs(!showLogs)}>
            {showLogs ? "Hide logs" : "View logs"}
          </button>
          {operatorUrl && data.view !== "plex" && (
            <p>
              <a href={operatorUrl} rel="noreferrer">
                {data.view === "plex" ? "Open Plex" : "Open qBittorrent"}
              </a>
              {data.view === "seedbox" &&
                " · Requires the SSH tunnel on this Windows PC. Existing qBittorrent login remains enabled."}
            </p>
          )}
          {showLogs && data.view === "plex" && appId && (
            <RemoteRuntimeLogs appId={appId} />
          )}
          {showLogs && data.view === "seedbox" && (
            <>
              <label>
                Component{" "}
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
                      {c === "seedbox" ? "Seedbox Agent" : c}
                    </option>
                  ))}
                </select>
              </label>
              <p className="muted">
                Safe, structured Agent diagnostics. Raw container output and
                credentials are never forwarded.
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
                    {stamp(e.timestamp)} · {e.severity} · {e.message}
                  </p>
                ))}
            </>
          )}
        </Panel>
      )}
    </div>
  );
}
