import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import {
  Activity as ActivityIcon,
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  Box,
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Cpu,
  Database,
  HardDrive,
  LayoutDashboard,
  LogOut,
  Menu,
  RefreshCw,
  Server,
  Settings2,
  ShieldCheck,
  Store,
  Terminal,
  Wrench,
  X,
} from "lucide-react";
import { api, setCsrf } from "./api";
import { bytes, uptime } from "./format";
import { SetupWizard } from "./wizard";
import { BackupsPage } from "./backups";
import { UpdatesPage } from "./updates";
import {
  AppRuntimePage,
  DeviceDiagnostics,
  RemoteRuntimeLogs,
  type Runtime,
} from "./runtime";
import { SeedboxInstallPage } from "./seedbox-install";
import { PlexInstallPage } from "./plex-install";
import { SecuritySettings } from "./security";
import { IntegrationsCard, IntegrationsPage } from "./integrations";
import { CloudflareTunnelCard } from "./cloudflare";
import { AppStorePage, CloudflareStorePage, FjordHubStorePage } from "./store";
import { HostsPage, LogicalStoragePanel } from "./hosts";
import {
  OperationProgress,
  type OperationState,
  type OperationStep,
} from "./operation-progress";
import {
  RuntimePanel,
  StorageSummary,
  SettingsExtensions,
  StorageWorkspace,
  MediaFiles,
} from "./phase2";
import type {
  Activity,
  AppInfo,
  DashboardSection,
  Log,
  Metrics,
  NavigationPath,
  Settings,
  Storage,
  User,
} from "./contracts";
import type { AgentStatus } from "./phase2-types";

const navigation = [
  ["/", "Dashboard", LayoutDashboard],
  ["/apps", "Apps", Box],
  ["/store", "App Store", Store],
  ["/storage", "Storage", HardDrive],
  ["/hosts", "Hosts", Server],
  ["/activity", "Activity", ActivityIcon],
  ["/logs", "Logs", Terminal],
  ["/updates", "Updates", RefreshCw],
  ["/backups", "Backups", Database],
  ["/integrations", "Integrations", Box],
  ["/settings", "Settings", Settings2],
] as const;

const simpleNavigation: NavigationPath[] = [
  "/",
  "/apps",
  "/store",
  "/storage",
  "/updates",
  "/backups",
  "/settings",
];
const detailedNavigation: NavigationPath[] = navigation.map(([path]) => path);
const simpleDashboard: DashboardSection[] = ["storage", "apps", "system"];
const detailedDashboard: DashboardSection[] = [
  "system",
  "storage",
  "apps",
  "activity",
  "network",
  "core",
  "runtime",
  "integrations",
  "cloudflare",
];

function useData<T>(path: string) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    setError("");
    const attempt = (number: number) => {
      api<T>(path)
        .then((value) => {
          setData(value);
          setError("");
        })
        .catch((e) => {
          if (number < 2)
            window.setTimeout(() => attempt(number + 1), 900 * (number + 1));
          else setError(e.message);
        });
    };
    attempt(0);
  }, [path]);
  useEffect(reload, [reload]);
  return { data, error, reload };
}

function Notice({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="notice">
      {children}
    </div>
  );
}
function Loading() {
  return (
    <div role="status" className="loading">
      <RefreshCw size={18} className="spin" /> Loading MediaHub…
    </div>
  );
}
function Badge({ value }: { value: string }) {
  return (
    <span className={`badge ${value}`}>
      <span aria-hidden="true" />
      {value}
    </span>
  );
}
function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="empty">
      <Box size={28} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function Section({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Application() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [setupRequired, setSetupRequired] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const refresh = useCallback(async () => {
    try {
      const status = await api<{ needsSetup: boolean }>("/auth/status");
      const installation = await api<{ setup_required: boolean }>(
        "/setup/status",
      );
      setSetupRequired(installation.setup_required);
      setNeedsSetup(status.needsSetup);
      if (!status.needsSetup) {
        try {
          const me = await api<User>("/auth/me");
          setCsrf(me.csrf);
          setUser(me);
        } catch {
          setUser(null);
        }
      }
      setConnectionError("");
    } catch {
      setConnectionError(
        "Cannot reach MediaHub. Check that the backend is running.",
      );
    } finally {
      setReady(true);
    }
  }, []);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    const expired = () => {
      setUser(null);
      setCsrf("");
    };
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  if (!ready) return <Loading />;
  if (setupRequired)
    return (
      <SetupWizard
        user={user}
        hasAdmin={!needsSetup}
        onSignedIn={(value) => {
          setCsrf(value.csrf);
          setUser(value);
          setNeedsSetup(false);
        }}
        onComplete={() => setSetupRequired(false)}
      />
    );
  if (!user)
    return (
      <Login
        needsSetup={needsSetup}
        error={connectionError}
        retry={refresh}
        onLogin={(value) => {
          setCsrf(value.csrf);
          setUser(value);
        }}
      />
    );
  return (
    <Shell
      user={user}
      onLogout={async () => {
        await api("/auth/logout", "POST");
        setUser(null);
        setCsrf("");
      }}
    />
  );
}

function Login({
  needsSetup,
  error: initialError,
  retry,
  onLogin,
}: {
  needsSetup: boolean;
  error: string;
  retry: () => void;
  onLogin: (user: User) => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      onLogin(
        await api<User>("/auth/login", "POST", {
          username: form.get("username"),
          password: form.get("password"),
          secondFactor: form.get("secondFactor") || "",
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="login-screen">
      <div className="login-panel">
        <Brand />
        <span className="eyebrow">YOUR LOCAL CONTROL ROOM</span>
        <h1>{needsSetup ? "A fresh foundation." : "Welcome back."}</h1>
        <p className="muted">
          {needsSetup
            ? "Create your administrator locally to unlock MediaHub."
            : "Sign in to manage your MediaHub."}
        </p>
        {(error || initialError) && <Notice>{error || initialError}</Notice>}
        {needsSetup ? (
          <div className="setup-instructions">
            <p>Run this in the new project’s terminal:</p>
            <code>python -m mediahub.cli admin</code>
            <p>
              Your password is entered privately. No default credentials are
              configured.
            </p>
            <button onClick={retry}>
              <RefreshCw size={16} /> Check again
            </button>
          </div>
        ) : (
          <form onSubmit={submit}>
            <label>
              Username
              <input
                autoComplete="username"
                name="username"
                required
                maxLength={80}
              />
            </label>
            <label>
              Password
              <input
                autoComplete="current-password"
                type="password"
                name="password"
                required
                maxLength={256}
              />
            </label>
            <label>
              Authenticator or recovery code
              <input
                autoComplete="one-time-code"
                name="secondFactor"
                maxLength={32}
                placeholder="If two-factor authentication is enabled"
              />
            </label>
            <button className="primary" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
              <ArrowUpRight size={17} />
            </button>
          </form>
        )}
        <div className="login-foot">
          <ShieldCheck size={16} /> Your private media workspace{" "}
          <span>v0.4.8</span>
        </div>
      </div>
    </main>
  );
}

function Brand() {
  return (
    <div className="brand">
      <img src="/favicon.svg" alt="" width="34" height="34" />
      <span>
        Media<span>Hub</span>
      </span>
    </div>
  );
}

function Shell({
  user,
  onLogout,
}: {
  user: User;
  onLogout: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [metrics, setMetrics] = useState<Metrics>();
  const [live, setLive] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [displayName, setDisplayName] = useState("MediaHub");
  const [advancedMode, setAdvancedMode] = useState(false);
  const [visibleNavigation, setVisibleNavigation] =
    useState<NavigationPath[]>(simpleNavigation);
  const [dashboardSections, setDashboardSections] =
    useState<DashboardSection[]>(simpleDashboard);
  const [appsExpanded, setAppsExpanded] = useState(true);
  const { data: navigationApps, reload: reloadNavigationApps } =
    useData<AppInfo[]>("/apps");
  const { data: updateSummary, reload: reloadUpdateSummary } = useData<{
    count: number;
  }>("/updates/summary");
  const location = useLocation();
  useEffect(() => {
    setOpen(false);
  }, [location]);
  useEffect(() => {
    const apply = () => {
      api<Settings>("/settings")
        .then((s) => {
          setDisplayName(s.display_name);
          setAdvancedMode(s.advanced_mode);
          setVisibleNavigation(s.visible_navigation);
          setDashboardSections(s.dashboard_sections);
          document.documentElement.dataset.theme = s.theme;
        })
        .catch(() => {});
    };
    apply();
    window.addEventListener("settings-changed", apply);
    return () => window.removeEventListener("settings-changed", apply);
  }, []);
  useEffect(() => {
    const source = new EventSource("/api/v1/events/stream");
    source.onopen = () => setLive(true);
    source.onerror = () => setLive(false);
    source.addEventListener("system.status", (event) => {
      setMetrics(JSON.parse((event as MessageEvent).data));
      setLive(true);
    });
    source.addEventListener("app.health.changed", () => {
      setRevision((n) => n + 1);
      reloadNavigationApps();
    });
    source.addEventListener("updates.changed", () => reloadUpdateSummary());
    source.addEventListener("session.expired", () => {
      source.close();
      window.dispatchEvent(new Event("session-expired"));
    });
    return () => source.close();
  }, [reloadNavigationApps, reloadUpdateSummary]);
  useEffect(() => {
    const refresh = () => {
      if (!document.hidden) reloadNavigationApps();
    };
    const timer = window.setInterval(refresh, 10000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [reloadNavigationApps]);
  const runtimePage = location.pathname.startsWith("/apps/");
  const storePage = location.pathname.startsWith("/store/");
  const title =
    navigation.find(([path]) => path === location.pathname)?.[1] ||
    (runtimePage ? "App runtime" : storePage ? "App Store" : "Dashboard");
  return (
    <div className="app-shell">
      {open && (
        <button
          className="scrim"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
        />
      )}
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <Brand />
        <p className="nav-label">WORKSPACE</p>
        <nav>
          {navigation
            .filter(([path]) => visibleNavigation.includes(path))
            .filter(([path]) => advancedMode || path !== "/hosts")
            .map(([path, label, Icon]) =>
              path === "/apps" ? (
                <div className="nav-app-group" key={path}>
                  <div className="nav-app-heading">
                    <NavLink to={path}>
                      <Icon size={19} />
                      <span>{label}</span>
                    </NavLink>
                    <button
                      type="button"
                      className="nav-expand"
                      aria-label={
                        appsExpanded
                          ? "Hide app shortcuts"
                          : "Show app shortcuts"
                      }
                      aria-expanded={appsExpanded}
                      onClick={() => setAppsExpanded((value) => !value)}
                    >
                      <ChevronDown size={16} />
                    </button>
                  </div>
                  {appsExpanded && (
                    <div className="app-shortcuts">
                      {(navigationApps || [])
                        .filter((app) => app.detailPath && !app.isMock)
                        .sort((left, right) =>
                          left.name.localeCompare(right.name),
                        )
                        .map((app) => (
                          <NavLink to={app.detailPath || "/apps"} key={app.id}>
                            <span
                              className={`app-shortcut-dot ${app.health.status}`}
                            />
                            <span>{app.name}</span>
                          </NavLink>
                        ))}
                      {!navigationApps && (
                        <span className="app-shortcuts-loading">
                          Loading apps…
                        </span>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <NavLink end={path === "/"} key={path} to={path}>
                  <Icon size={19} />
                  <span>{label}</span>
                  {path === "/" && <span className="nav-shortcut">01</span>}
                  {path === "/updates" && !!updateSummary?.count && (
                    <span
                      className="nav-update-count"
                      aria-label={`${updateSummary.count} updates available`}
                    >
                      {updateSummary.count > 99 ? "99+" : updateSummary.count}
                    </span>
                  )}
                </NavLink>
              ),
            )}
        </nav>
        <div className="sidebar-bottom">
          <div className="preview-label">
            <Box size={16} />
            <div>
              Your media workspace<small>Apps · Storage · Protection</small>
            </div>
          </div>
          <div className="profile">
            <span className="avatar">
              {user.username.slice(0, 1).toUpperCase()}
            </span>
            <div>
              {user.username}
              <small>Administrator</small>
            </div>
            <button
              className="icon-button"
              title="Sign out"
              aria-label="Sign out"
              onClick={() => {
                onLogout().catch((e) => setError(e.message));
              }}
            >
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu icon-button"
              aria-label={open ? "Close navigation" : "Open navigation"}
              onClick={() => setOpen(!open)}
            >
              {open ? <X /> : <Menu />}
            </button>
            <span>{displayName}</span>
            <ChevronRight size={15} />
            <strong>{title}</strong>
          </div>
          <div className="topbar-right">
            <Badge value={live ? "live" : "reconnecting"} />
            <span className="version">v{metrics?.version || "0.4.8"}</span>
          </div>
        </header>
        <main className="main-content">
          {!runtimePage && (
            <div className="page-heading">
              <div>
                <span className="eyebrow">
                  {title === "Dashboard" ? "CONTROL ROOM" : "WORKSPACE"}
                </span>
                <h1>
                  {title === "Dashboard" ? "Everything, in view." : title}
                </h1>
                <p>
                  {title === "Dashboard"
                    ? "A live overview of your MediaHub environment."
                    : pageDescription(title)}
                </p>
              </div>
              {metrics && advancedMode && (
                <div className="host-chip">
                  <Server size={17} />
                  <span>
                    MediaHub Core
                    <small title={metrics.hostname}>
                      Technical runtime details
                    </small>
                  </span>
                </div>
              )}
            </div>
          )}
          {error && <Notice>{error}</Notice>}
          {!live && (
            <Notice>
              Live connection interrupted. Reconnecting automatically; displayed
              metrics may be stale.
            </Notice>
          )}
          <Routes>
            <Route path="/apps/install/plex" element={<PlexInstallPage />} />
            <Route
              path="/apps/install/seedbox"
              element={<SeedboxInstallPage />}
            />
            <Route
              path="/apps/:appId/install"
              element={<SeedboxInstallPage />}
            />
            <Route path="/apps/:appId" element={<AppRuntimePage />} />
            <Route path="/store/cloudflare" element={<CloudflareStorePage />} />
            <Route path="/store/fjordhub" element={<FjordHubStorePage />} />
            <Route path="/store" element={<AppStorePage />} />
            <Route
              path="/"
              element={
                <Dashboard
                  metrics={metrics}
                  revision={revision}
                  live={live}
                  sections={dashboardSections}
                />
              }
            />
            <Route
              path="/apps"
              element={
                <div className="stack">
                  <Apps revision={revision} />
                  <section className="store-callout">
                    <div>
                      <strong>Looking for another app?</strong>
                      <p>
                        Browse guided installations without mixing them into the
                        apps you already run.
                      </p>
                    </div>
                    <NavLink className="primary" to="/store">
                      Open App Store →
                    </NavLink>
                  </section>
                </div>
              }
            />
            <Route
              path="/storage"
              element={
                <div className="stack">
                  <MediaFiles />
                  <StorageSummary />
                  {advancedMode && (
                    <details className="technical-disclosure">
                      <summary>Technical storage mappings</summary>
                      <div className="stack">
                        <LogicalStoragePanel />
                        <StorageWorkspace />
                      </div>
                    </details>
                  )}
                </div>
              }
            />
            <Route path="/hosts" element={<HostsPage />} />
            <Route path="/integrations" element={<IntegrationsPage />} />
            <Route
              path="/activity"
              element={<ActivityPage revision={revision} />}
            />
            <Route path="/logs" element={<Logs />} />
            <Route
              path="/settings"
              element={
                <SettingsExtensions
                  general={<SettingsPage />}
                  maintenance={<MaintenancePage />}
                  security={<SecuritySettings />}
                  advanced={advancedMode}
                />
              }
            />
            <Route path="/updates" element={<UpdatesPage />} />
            <Route path="/backups" element={<BackupsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          <footer className="footer">
            <span>
              MediaHub Core <span className="muted">/</span>{" "}
              {metrics?.version || "0.4.8"}
            </span>
            <span>Self-hosted · Your media, your control</span>
          </footer>
        </main>
      </div>
    </div>
  );
}

function pageDescription(title: string) {
  return (
    {
      Apps: "One place for your apps, their status and controls.",
      "App Store": "Add apps through guided, security-aware setup flows.",
      Storage: "Registered locations. Your files stay exactly where they are.",
      Activity: "A timeline of events in this MediaHub installation.",
      Logs: "Recent Core diagnostics, without secrets or production logs.",
      Settings: "Make this workspace yours.",
      Updates: "Keep track of platform and app versions.",
      Backups: "Configuration protection and recovery.",
    } as Record<string, string>
  )[title];
}

function MetricCard({
  icon,
  label,
  value,
  detail,
  percent,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
  percent?: number | null;
}) {
  return (
    <div className="metric-card">
      <div className="metric-label">
        {icon}
        <span>{label}</span>
      </div>
      <div className="metric-value">{value}</div>
      <p>{detail}</p>
      {percent != null ? (
        <div
          className={`meter ${percent > 90 ? "warning" : ""}`}
          role="meter"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(percent)}
        >
          <span style={{ width: `${Math.max(0, Math.min(percent, 100))}%` }} />
        </div>
      ) : (
        <div className="metric-baseline" />
      )}
    </div>
  );
}

function Dashboard({
  metrics: m,
  revision,
  live,
  sections,
}: {
  metrics?: Metrics;
  revision: number;
  live: boolean;
  sections: DashboardSection[];
}) {
  const { data: apps, error, reload } = useData<AppInfo[]>("/apps");
  useEffect(reload, [revision, reload]);
  const {
    data: recentActivity,
    error: activityError,
    reload: reloadActivity,
  } = useData<Activity[]>("/events/history?limit=4");
  useEffect(() => {
    reloadActivity();
  }, [revision, reloadActivity]);
  if (!m) return <Loading />;
  const visible = new Set(sections);
  const hasRightColumn = visible.has("core") || visible.has("network");
  return (
    <>
      {error && <Notice>{error}</Notice>}
      {sections.length > 0 && (
        <div className={`dashboard-columns ${hasRightColumn ? "" : "single"}`}>
          <div className="stack">
            {visible.has("storage") && <StorageSummary />}
            {visible.has("apps") && (
              <Section
                title="Your apps"
                aside={
                  <NavLink className="text-link" to="/apps">
                    View apps <ArrowUpRight size={15} />
                  </NavLink>
                }
              >
                <div className="app-totals">
                  {[
                    ["Installed", apps?.length ?? 0],
                    [
                      "Healthy",
                      apps?.filter((a) => a.health.status === "healthy")
                        .length ?? 0,
                    ],
                    [
                      "Needs attention",
                      apps?.filter((a) =>
                        ["degraded", "unhealthy"].includes(a.health.status),
                      ).length ?? 0,
                    ],
                    [
                      "Unknown",
                      apps?.filter((a) => a.health.status === "unknown")
                        .length ?? 0,
                    ],
                  ].map(([label, n]) => (
                    <div key={label}>
                      <strong>{n}</strong>
                      <span>{label}</span>
                    </div>
                  ))}
                </div>
                {apps?.map((app) => (
                  <div className="app-row" key={app.id}>
                    <div className="app-icon">
                      <Box size={23} />
                    </div>
                    <div className="app-row-name">
                      <strong>{app.name}</strong>
                      <small>
                        {app.isMock ? "Mock adapter" : "Installed"} · v
                        {app.version}
                      </small>
                    </div>
                    <Badge value={app.health.status} />
                  </div>
                ))}
                {!apps?.length && (
                  <Empty title="No apps installed">
                    Apps will appear here when registered.
                  </Empty>
                )}
                <div className="panel-note">
                  <ShieldCheck size={16} />{" "}
                  {apps?.some((a) => a.isMock)
                    ? "Development mock only. No real services controlled."
                    : apps?.length
                      ? "Apps are monitored through paired Agents or restricted read-only integrations."
                      : "No apps installed."}
                </div>
              </Section>
            )}
            {visible.has("activity") && (
              <Section
                title="Recent activity"
                aside={
                  <NavLink className="text-link" to="/activity">
                    Full timeline <ArrowUpRight size={15} />
                  </NavLink>
                }
              >
                <ActivityList items={recentActivity || []} />
                {activityError && <Notice>{activityError}</Notice>}
              </Section>
            )}
            {visible.has("system") && (
              <details className="system-overview">
                <summary>
                  <span className="system-summary-icon">
                    <Cpu size={18} />
                  </span>
                  <span>
                    <strong>System details</strong>
                    <small>
                      Core resource use, uptime and app runtime status
                    </small>
                  </span>
                  <Badge value={live ? "healthy" : "unknown"} />
                  <ChevronDown className="disclosure-chevron" size={18} />
                </summary>
                <div className="system-overview-body">
                  <div className="compact-metrics">
                    <MetricCard
                      icon={<Cpu size={18} />}
                      label="Core CPU"
                      value={
                        m.cpu.percent == null
                          ? "Sampling…"
                          : `${m.cpu.percent.toFixed(1)}%`
                      }
                      detail={`${m.cpu.cores} allocated cores`}
                      percent={m.cpu.percent}
                    />
                    <MetricCard
                      icon={<Server size={18} />}
                      label="Core memory"
                      value={bytes(m.ram.usedBytes)}
                      detail={`${bytes(m.ram.availableBytes)} available`}
                      percent={m.ram.percent}
                    />
                    <MetricCard
                      icon={<Clock3 size={18} />}
                      label="Core uptime"
                      value={uptime(m.coreUptimeSeconds)}
                      detail={`Guest uptime ${uptime(m.uptimeSeconds)}`}
                    />
                  </div>
                  <div className="system-detail-lines">
                    <StatusLine
                      label="Core system disk"
                      value={`${bytes(m.disk.freeBytes)} free of ${bytes(m.disk.totalBytes)}`}
                    />
                    {(apps || []).map((app) => (
                      <StatusLine
                        key={app.id}
                        label={app.name}
                        value={`${app.state} · ${app.health.status}`}
                      />
                    ))}
                  </div>
                  <p className="muted">
                    These numbers describe MediaHub Core, not the complete
                    Proxmox server. Open an app for its own verified runtime
                    details.
                  </p>
                </div>
              </details>
            )}
            {visible.has("runtime") && <RuntimePanel />}
            {visible.has("integrations") && <IntegrationsCard />}
            {visible.has("cloudflare") && <CloudflareTunnelCard />}
          </div>
          {hasRightColumn && (
            <div className="stack">
              {visible.has("core") && (
                <Section
                  title="Core status"
                  aside={<Badge value={live ? "healthy" : "unknown"} />}
                >
                  <div className="status-rows">
                    <StatusLine
                      label="Backend API"
                      value={live ? "Connected" : "Disconnected"}
                    />
                    <StatusLine
                      label="Realtime"
                      value={live ? "Streaming · SSE" : "Reconnecting"}
                    />
                    <StatusLine
                      label="Runtime control"
                      value="Agent-verified actions"
                    />
                    <StatusLine label="Public ingress" value="Not managed" />
                    <StatusLine label="Release" value={m.version} />
                  </div>
                </Section>
              )}
              {visible.has("network") && (
                <Section title="Network throughput">
                  <div className="network-card">
                    <div>
                      <ArrowDown size={19} />
                      <span>Download</span>
                      <strong>
                        {bytes(m.network.downloadBytesPerSecond)}
                        <small>/s</small>
                      </strong>
                    </div>
                    <div>
                      <ArrowUp size={19} />
                      <span>Upload</span>
                      <strong>
                        {bytes(m.network.uploadBytesPerSecond)}
                        <small>/s</small>
                      </strong>
                    </div>
                  </div>
                  <div className="panel-note">
                    Runtime network totals, not torrent speeds.
                  </div>
                </Section>
              )}
            </div>
          )}
        </div>
      )}
    </>
  );
}

function StatusLine({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
function ActivityList({ items }: { items: Activity[] }) {
  return items.length ? (
    <div className="activity-list">
      {items.map((item) => (
        <div className="activity-item" key={item.id}>
          <div className="activity-icon">
            <Check size={15} />
          </div>
          <div>
            <strong>{item.message}</strong>
            <small>
              {item.event} · {item.severity}
            </small>
          </div>
          <time dateTime={item.timestamp}>
            {new Date(item.timestamp).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </time>
        </div>
      ))}
    </div>
  ) : (
    <Empty title="No activity yet">New events will appear here.</Empty>
  );
}

function Apps({ revision }: { revision: number }) {
  const { data, error, reload } = useData<AppInfo[]>("/apps");
  const [actionError, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(reload, [revision, reload]);
  const act = async (id: string, action: string) => {
    setBusy(true);
    setError("");
    try {
      await api(`/apps/${id}/actions/${action}`, "POST");
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      {(error || actionError) && <Notice>{error || actionError}</Notice>}
      {!data ? (
        <div
          className="apps-grid app-skeleton-grid"
          aria-busy="true"
          aria-label="Loading apps"
        >
          {[0, 1].map((item) => (
            <div className="panel app-skeleton" key={item}>
              <span />
              <span />
              <span />
            </div>
          ))}
        </div>
      ) : data.length ? (
        <div className="apps-grid">
          {[...data]
            .sort((left, right) => left.name.localeCompare(right.name))
            .map((app) => (
              <section className="panel app-detail" key={app.id}>
                <div className="panel-heading">
                  <div className="app-icon">
                    <Box />
                  </div>
                  <Badge value={app.health.status} />
                </div>
                <h2>{app.name}</h2>
                <p className="muted">
                  {app.packageId} · {app.version}
                </p>
                <p>{app.health.summary}</p>
                {app.isMock && (
                  <div className="mock-callout">
                    TEST APP · No real container or media access
                  </div>
                )}
                {!app.isMock && (
                  <p className="muted">
                    {app.packageId === "org.mediahub.cloudflared"
                      ? "Installed · Read-only infrastructure monitor"
                      : "Installed · Paired Agent runtime"}
                  </p>
                )}
                {app.detailPath && (
                  <NavLink className="text-link" to={app.detailPath}>
                    Open {app.name} →
                  </NavLink>
                )}
                {app.isMock && (
                  <div className="button-row">
                    <button
                      disabled={busy || app.state === "running"}
                      onClick={() => act(app.id, "start")}
                    >
                      Start
                    </button>
                    <button
                      disabled={busy || app.state === "stopped"}
                      onClick={() => act(app.id, "stop")}
                    >
                      Stop
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => act(app.id, "restart")}
                    >
                      Restart
                    </button>
                  </div>
                )}
              </section>
            ))}
        </div>
      ) : (
        <Empty title="No apps installed">The app registry is empty.</Empty>
      )}
    </>
  );
}

export function LegacyStoragePage() {
  const { data, error, reload } = useData<Storage[]>("/storage");
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFailure("");
    setMessage("");
    setBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      await api("/storage", "POST", {
        name: form.get("name"),
        kind: form.get("kind"),
        path: form.get("path"),
      });
      setMessage("Location registered. No files were changed.");
      reload();
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="stack">
      {(error || failure) && <Notice>{error || failure}</Notice>}
      {message && (
        <div role="status" className="success">
          {message}
        </div>
      )}
      <Section title="Storage locations">
        {!data ? (
          <Loading />
        ) : !data.length ? (
          <Empty title="No locations registered">
            Your existing media has not been imported. Register only paths
            allowed by MEDIAHUB_STORAGE_ROOTS.
          </Empty>
        ) : (
          data.map((item) => (
            <div className="storage-row" key={item.id}>
              <HardDrive />
              <div>
                <strong>{item.name}</strong>
                <code>{item.path}</code>
                <small>
                  {item.kind} · Read: {item.readable ? "yes" : "no"} · Write
                  permission: {item.writable ? "reported" : "no"}
                </small>
              </div>
              <span>{bytes(item.freeBytes)} free</span>
              <Badge value={item.exists ? "available" : "unavailable"} />
            </div>
          ))
        )}
      </Section>
      <Section title="Register existing location">
        <form className="storage-form" onSubmit={submit}>
          <label>
            Name
            <input name="name" required maxLength={80} />
          </label>
          <label>
            Type
            <select name="kind">
              <option value="appdata">App data</option>
              <option value="downloads">Downloads</option>
              <option value="movies">Movies</option>
              <option value="tv">TV shows</option>
              <option value="backups">Backups</option>
              <option value="custom">Custom</option>
            </select>
          </label>
          <label className="wide">
            Absolute path
            <input
              name="path"
              required
              placeholder="An existing path inside an allowed storage root"
            />
          </label>
          <p className="muted wide">
            Read-only inspection. Write permission is advisory; no test files
            are created.
          </p>
          <button disabled={busy} className="primary">
            {busy ? "Checking…" : "Validate & register"}
          </button>
        </form>
      </Section>
    </div>
  );
}

function ActivityPage({ revision }: { revision: number }) {
  const { data, error, reload } = useData<Activity[]>("/events/history");
  useEffect(reload, [revision, reload]);
  return (
    <Section
      title="Event timeline"
      aside={
        <button onClick={reload}>
          <RefreshCw size={15} /> Refresh
        </button>
      }
    >
      {error && <Notice>{error}</Notice>}
      {!data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Event / message</th>
                <th>Source</th>
                <th>Severity</th>
              </tr>
            </thead>
            <tbody>
              {data.map((item) => (
                <tr key={item.id}>
                  <td>
                    <time>{new Date(item.timestamp).toLocaleString()}</time>
                  </td>
                  <td>
                    <strong>{item.event}</strong>
                    <small>{item.message}</small>
                  </td>
                  <td className="source-cell">{item.source}</td>
                  <td>
                    <Badge value={item.severity} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!data.length && (
            <Empty title="No events yet">Activity will appear here.</Empty>
          )}
        </div>
      )}
    </Section>
  );
}

function Logs() {
  const [source, setSource] = useState("core");
  const { data: apps } = useData<AppInfo[]>("/apps");
  const { data, error, reload } = useData<Log[]>("/logs");
  if (source !== "core")
    return (
      <div className="stack">
        <button onClick={() => setSource("core")}>
          ← Core logs / choose source
        </button>
        <RemoteRuntimeLogs appId={source} />
      </div>
    );
  return (
    <Section
      title="Core log buffer"
      aside={
        <button onClick={reload}>
          <RefreshCw size={15} /> Refresh
        </button>
      }
    >
      <label>
        Log source{" "}
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="core">MediaHub Core</option>
          {apps
            ?.filter((a) => a.detailPath)
            .map((a) => (
              <option value={a.id} key={a.id}>
                {a.name} Agent / components
              </option>
            ))}
        </select>
      </label>
      {error && <Notice>{error}</Notice>}
      <div className="log-output">
        {data?.map((log, i) => (
          <div key={i}>
            <time>{new Date(log.timestamp).toLocaleTimeString()}</time>
            <span>{log.level}</span>
            <span>{log.component}</span>
            <p>{log.message}</p>
          </div>
        ))}
        {data?.length === 0 && (
          <Empty title="No log entries">
            Only this Core process is connected.
          </Empty>
        )}
      </div>
    </Section>
  );
}

function SettingsPage() {
  const { data, error } = useData<Settings>("/settings");
  const [draft, setDraft] = useState<Settings>();
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (data) setDraft(data);
  }, [data]);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFailure("");
    setMessage("");
    setBusy(true);
    if (!draft) return;
    try {
      await api("/settings", "PUT", draft);
      setMessage("Your view has been saved.");
      window.dispatchEvent(new Event("settings-changed"));
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Section title="Workspace preferences">
      {(error || failure) && <Notice>{error || failure}</Notice>}
      {message && (
        <div role="status" className="success">
          {message}
        </div>
      )}
      {!draft ? (
        <Loading />
      ) : (
        <form className="settings-form" onSubmit={submit}>
          <label>
            Workspace name
            <input
              name="display_name"
              value={draft.display_name}
              onChange={(event) =>
                setDraft({ ...draft, display_name: event.target.value })
              }
              required
              maxLength={60}
            />
          </label>
          <label>
            Appearance
            <select
              name="theme"
              value={draft.theme}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  theme: event.target.value as Settings["theme"],
                })
              }
            >
              <option value="dark">Dark</option>
              <option value="light">Light</option>
              <option value="system">System</option>
            </select>
          </label>
          <label>
            Activity page size
            <input
              name="activity_page_size"
              type="number"
              min={10}
              max={100}
              value={draft.activity_page_size}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  activity_page_size: Number(event.target.value),
                })
              }
              required
            />
          </label>
          <label>
            GitHub release repository
            <input
              name="release_repository"
              value={draft.release_repository || ""}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  release_repository: event.target.value || null,
                })
              }
              placeholder="owner/mediahub"
              pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}"
            />
            <small>
              Public or private repository used only for verified MediaHub
              releases. Configure encrypted private access on the Updates page.
            </small>
          </label>
          <label>
            Automatic update checks
            <select
              name="update_check_interval_hours"
              value={draft.update_check_interval_hours}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  update_check_interval_hours: Number(
                    event.target.value,
                  ) as Settings["update_check_interval_hours"],
                })
              }
            >
              <option value={0}>Off</option>
              <option value={1}>Every hour</option>
              <option value={6}>Every 6 hours</option>
              <option value={12}>Every 12 hours</option>
              <option value={24}>Every day</option>
              <option value={72}>Every 3 days</option>
              <option value={168}>Every week</option>
            </select>
            <small>
              Checks only release metadata. Updates are installed only after
              explicit approval.
            </small>
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              name="advanced_mode"
              checked={draft.advanced_mode}
              onChange={(event) =>
                setDraft({ ...draft, advanced_mode: event.target.checked })
              }
            />{" "}
            Technical mode: show server, network and diagnostic settings
          </label>
          <div className="visibility-settings">
            <div className="visibility-heading">
              <div>
                <h3>Choose your menu</h3>
                <p>Dashboard and Settings always stay available.</p>
              </div>
              <div className="button-row">
                <button
                  type="button"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      visible_navigation: simpleNavigation,
                      advanced_mode: false,
                    })
                  }
                >
                  Simple view
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      visible_navigation: detailedNavigation,
                      advanced_mode: true,
                    })
                  }
                >
                  Show everything
                </button>
              </div>
            </div>
            <div className="choice-grid">
              {navigation.map(([path, label, Icon]) => {
                const required = path === "/" || path === "/settings";
                return (
                  <label className="choice-card" key={path}>
                    <input
                      type="checkbox"
                      checked={draft.visible_navigation.includes(path)}
                      disabled={required}
                      onChange={(event) => {
                        const visible = event.target.checked
                          ? [...draft.visible_navigation, path]
                          : draft.visible_navigation.filter(
                              (candidate) => candidate !== path,
                            );
                        setDraft({ ...draft, visible_navigation: visible });
                      }}
                    />
                    <Icon size={18} />
                    <span>
                      <strong>{label}</strong>
                      <small>{navigationHelp[path]}</small>
                    </span>
                  </label>
                );
              })}
            </div>
          </div>
          <div className="visibility-settings">
            <div className="visibility-heading">
              <div>
                <h3>Choose your dashboard</h3>
                <p>Only selected cards are shown on the front page.</p>
              </div>
              <div className="button-row">
                <button
                  type="button"
                  onClick={() =>
                    setDraft({ ...draft, dashboard_sections: simpleDashboard })
                  }
                >
                  Simple dashboard
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      dashboard_sections: detailedDashboard,
                    })
                  }
                >
                  All cards
                </button>
              </div>
            </div>
            <div className="choice-grid">
              {dashboardChoices.map(([section, label, help]) => (
                <label className="choice-card" key={section}>
                  <input
                    type="checkbox"
                    checked={draft.dashboard_sections.includes(section)}
                    disabled={
                      draft.dashboard_sections.length === 1 &&
                      draft.dashboard_sections[0] === section
                    }
                    onChange={(event) => {
                      const visible = event.target.checked
                        ? [...draft.dashboard_sections, section]
                        : draft.dashboard_sections.filter(
                            (candidate) => candidate !== section,
                          );
                      setDraft({ ...draft, dashboard_sections: visible });
                    }}
                  />
                  <span>
                    <strong>{label}</strong>
                    <small>{help}</small>
                  </span>
                </label>
              ))}
            </div>
          </div>
          <button className="primary" disabled={busy}>
            {busy ? "Saving…" : "Save preferences"}
          </button>
          <p className="muted">
            Network, proxy trust and allowed storage roots are configured
            server-side. Secrets are never returned here.
          </p>
        </form>
      )}
    </Section>
  );
}

type MaintenanceState = "healthy" | "degraded" | "unknown";

function MaintenanceCard({
  icon,
  title,
  state,
  detail,
}: {
  icon: ReactNode;
  title: string;
  state: MaintenanceState;
  detail: string;
}) {
  return (
    <article className="maintenance-card">
      <div className="maintenance-card-head">
        <span className="maintenance-card-icon">{icon}</span>
        <Badge value={state} />
      </div>
      <div>
        <h3>{title}</h3>
        <p>{detail}</p>
      </div>
    </article>
  );
}

function SeedboxDeviceMaintenance({ appId }: { appId: string }) {
  const { data, error, reload } = useData<{
    view: string;
    report: Runtime;
  }>(`/apps/${appId}/runtime`);
  return (
    <details className="maintenance-device-details">
      <summary>
        <span>
          <strong>Seedbox device diagnostics</strong>
          <small>
            Disk identity and mount details for troubleshooting only
          </small>
        </span>
        <ChevronDown size={17} />
      </summary>
      <div className="maintenance-device-content">
        <div className="runtime-toolbar">
          <p className="muted">
            These technical details stay hidden during normal daily use.
          </p>
          <button type="button" onClick={reload}>
            <RefreshCw size={15} /> Refresh devices
          </button>
        </div>
        {error && <Notice>{error}</Notice>}
        {!data && !error && <Loading />}
        {data?.view === "seedbox" && <DeviceDiagnostics report={data.report} />}
      </div>
    </details>
  );
}

function MaintenancePage() {
  const core = useData<{ status: string; version: string }>("/health");
  const runtime = useData<AgentStatus>("/runtime");
  const storage = useData<Storage[]>("/storage/locations");
  const apps = useData<AppInfo[]>("/apps");
  const [checking, setChecking] = useState(false);
  const [operation, setOperation] = useState<OperationState>();
  const [snapshot, setSnapshot] = useState<{
    core?: { status: string; version: string };
    runtime?: AgentStatus;
    storage?: Storage[];
    apps?: AppInfo[];
  }>({});

  const coreData = snapshot.core || core.data;
  const runtimeData = snapshot.runtime || runtime.data;
  const storageData = snapshot.storage || storage.data;
  const appsData = snapshot.apps || apps.data;

  const storageState: MaintenanceState = !storageData
    ? "unknown"
    : storageData.length > 0 &&
        storageData.every((location) => location.exists && location.readable)
      ? "healthy"
      : "degraded";
  const appProblems =
    appsData?.filter((app) =>
      ["degraded", "unhealthy"].includes(app.health.status),
    ) || [];
  const appsState: MaintenanceState = !appsData
    ? "unknown"
    : appProblems.length === 0
      ? appsData.every((app) => app.health.status === "healthy")
        ? "healthy"
        : "unknown"
      : "degraded";
  const failure =
    core.error || runtime.error || storage.error || apps.error || "";
  const seedboxApp = appsData?.find(
    (app) => app.packageId === "org.mediahub.seedbox",
  );

  const runCheck = async () => {
    const steps: OperationStep[] = [
      { label: "Check MediaHub Core", state: "pending" },
      { label: "Check Agent runtime", state: "pending" },
      { label: "Validate registered storage", state: "pending" },
      { label: "Check installed apps", state: "pending" },
    ];
    const details: string[] = [];
    let activeStep = 0;
    const publish = (
      progress: number,
      status: OperationState["status"],
      message: string,
    ) =>
      setOperation({
        title: "Maintenance check",
        status,
        progress,
        message,
        steps: steps.map((step) => ({ ...step })),
        details: [...details],
      });

    setChecking(true);
    steps[0].state = "running";
    publish(5, "running", "Checking MediaHub Core…");
    try {
      const coreResult = await api<{ status: string; version: string }>(
        "/health",
      );
      setSnapshot((current) => ({ ...current, core: coreResult }));
      steps[0].state = coreResult.status === "healthy" ? "complete" : "error";
      details.push(`GET /health · ${coreResult.status}`);

      activeStep = 1;
      steps[1].state = "running";
      publish(30, "running", "Checking the local Agent connection…");
      const runtimeResult = await api<AgentStatus>("/runtime");
      setSnapshot((current) => ({ ...current, runtime: runtimeResult }));
      steps[1].state = runtimeResult.connected ? "complete" : "error";
      details.push(
        `GET /runtime · ${runtimeResult.connected ? "connected" : "disconnected"}`,
      );

      activeStep = 2;
      steps[2].state = "running";
      publish(55, "running", "Validating MediaHub storage locations…");
      const storageResult = await api<Storage[]>("/storage/locations");
      setSnapshot((current) => ({ ...current, storage: storageResult }));
      const availableStorage = storageResult.filter(
        (item) => item.exists && item.readable,
      ).length;
      steps[2].state =
        storageResult.length > 0 && availableStorage === storageResult.length
          ? "complete"
          : "error";
      details.push(
        `GET /storage/locations · ${availableStorage}/${storageResult.length} available`,
      );

      activeStep = 3;
      steps[3].state = "running";
      publish(80, "running", "Checking installed app health…");
      const appResult = await api<AppInfo[]>("/apps");
      setSnapshot((current) => ({ ...current, apps: appResult }));
      const unhealthyApps = appResult.filter(
        (app) => app.health.status !== "healthy",
      ).length;
      steps[3].state = unhealthyApps === 0 ? "complete" : "error";
      details.push(
        `GET /apps · ${appResult.length - unhealthyApps}/${appResult.length} healthy`,
      );

      const degraded =
        coreResult.status !== "healthy" ||
        !runtimeResult.connected ||
        storageResult.length === 0 ||
        availableStorage !== storageResult.length ||
        unhealthyApps > 0;
      publish(
        100,
        degraded ? "error" : "success",
        degraded
          ? "The check completed and found items that need attention."
          : "All maintenance checks completed successfully.",
      );
    } catch {
      steps[activeStep].state = "error";
      details.push(
        "Request failed · see the warning above for the safe error message",
      );
      publish(100, "error", "The maintenance check could not be completed.");
    } finally {
      setChecking(false);
      core.reload();
      runtime.reload();
      storage.reload();
      apps.reload();
    }
  };

  return (
    <div className="stack">
      <Section
        title="Maintenance"
        aside={
          <button
            className="maintenance-check"
            type="button"
            onClick={() => void runCheck()}
            disabled={checking}
          >
            <RefreshCw size={15} className={checking ? "spin" : ""} />
            {checking ? "Checking…" : "Run maintenance check"}
          </button>
        }
      >
        <div className="maintenance-hero">
          <span className="maintenance-hero-icon">
            <Wrench size={24} />
          </span>
          <div>
            <h3>Keep MediaHub healthy</h3>
            <p>
              Check the platform, apps and storage from one safe workspace.
              Nothing is deleted or restarted by this check.
            </p>
          </div>
        </div>
        {failure && <Notice>{failure}</Notice>}
        {operation && <OperationProgress operation={operation} />}
        <div className="maintenance-grid">
          <MaintenanceCard
            icon={<Server size={19} />}
            title="MediaHub Core"
            state={
              !coreData
                ? "unknown"
                : coreData.status === "healthy"
                  ? "healthy"
                  : "degraded"
            }
            detail={
              coreData
                ? `Version ${coreData.version} is responding.`
                : "Waiting for the Core health check."
            }
          />
          <MaintenanceCard
            icon={<ActivityIcon size={19} />}
            title="Agent runtime"
            state={
              !runtimeData
                ? "unknown"
                : runtimeData.connected
                  ? "healthy"
                  : "degraded"
            }
            detail={
              runtimeData?.connected
                ? `${runtimeData.hostname || "Local agent"} is connected.`
                : runtimeData?.message || "Waiting for the Agent health check."
            }
          />
          <MaintenanceCard
            icon={<HardDrive size={19} />}
            title="Storage"
            state={storageState}
            detail={
              storageData
                ? `${storageData.filter((item) => item.exists && item.readable).length} of ${storageData.length} locations are available.`
                : "Waiting for the storage health check."
            }
          />
          <MaintenanceCard
            icon={<Box size={19} />}
            title="Installed apps"
            state={appsState}
            detail={
              appsData
                ? appProblems.length
                  ? `${appProblems.length} app${appProblems.length === 1 ? " needs" : "s need"} attention.`
                  : `${appsData.length} app${appsData.length === 1 ? " is" : "s are"} healthy.`
                : "Waiting for the app health check."
            }
          />
        </div>
      </Section>

      <Section title="Maintenance tools">
        <div className="maintenance-actions">
          <NavLink className="maintenance-action" to="/storage">
            <HardDrive size={20} />
            <span>
              <strong>Storage</strong>
              <small>Review capacity, folders and media files</small>
            </span>
            <ChevronRight size={17} />
          </NavLink>
          <NavLink className="maintenance-action" to="/updates">
            <RefreshCw size={20} />
            <span>
              <strong>Updates</strong>
              <small>Check verified MediaHub and app releases</small>
            </span>
            <ChevronRight size={17} />
          </NavLink>
          <NavLink className="maintenance-action" to="/backups">
            <Database size={20} />
            <span>
              <strong>Configuration backups</strong>
              <small>Protect settings without duplicating media</small>
            </span>
            <ChevronRight size={17} />
          </NavLink>
        </div>
        <div className="maintenance-safety">
          <ShieldCheck size={21} />
          <div>
            <strong>Media stays protected</strong>
            <p>
              Maintenance never removes movies, TV series, downloads or app data
              automatically. Cleanup actions are limited to explicitly listed
              disposable files and always ask for a clear confirmation before
              anything is deleted.
            </p>
          </div>
        </div>
        {seedboxApp && <SeedboxDeviceMaintenance appId={seedboxApp.id} />}
      </Section>
    </div>
  );
}

const navigationHelp: Record<NavigationPath, string> = {
  "/": "Your front page",
  "/apps": "Plex, Seedbox and future apps",
  "/store": "Add apps with guided setup",
  "/storage": "Browse media and check disk space",
  "/hosts": "Technical server and container details",
  "/activity": "A timeline of changes",
  "/logs": "Technical messages for troubleshooting",
  "/updates": "Available MediaHub software updates",
  "/backups": "Protect MediaHub settings",
  "/integrations": "Connections such as FjordHub",
  "/settings": "Appearance, security and this layout",
};

const dashboardChoices: [DashboardSection, string, string][] = [
  [
    "system",
    "System details",
    "Collapsed Core resources, uptime and app status",
  ],
  ["storage", "Storage", "Your configured disks and available space"],
  ["apps", "Apps", "Status for Plex, Seedbox and other apps"],
  ["activity", "Recent activity", "The latest MediaHub events"],
  ["network", "Network", "Technical Core network traffic"],
  ["core", "Core health", "Connection and runtime diagnostics"],
  ["runtime", "App runtime", "Technical Agent and Docker status"],
  ["integrations", "Integrations", "Status for optional connections"],
  [
    "cloudflare",
    "Cloudflare Tunnel",
    "Tunnel connection and public route health",
  ],
];
