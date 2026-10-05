import { fjordHubLink } from "./fjordhub-token-guide";
import { canRunMaintenance, installedAppsHealth, type MaintenanceState } from "./maintenance-health";
import { getLocale, translateText, setLanguage, t, useLanguage } from "./i18n";

import { LanguageSettings } from "./language-settings";
import { AppearanceSettings } from "./appearance-settings";
import { setAccountAppearance, useAppearanceTheme } from "./appearance";
import {
  ControlSummary,
  ControlStatus,
  ServiceOverview,
  ResourceTrends,
  useServiceReports,
  useMetricHistory,
} from "./control-center";
import { WorkspaceSearch } from "./workspace-search";
import { ServiceIcon } from "./service-icon";
import { useDashboardData } from "./dashboard-data";
import { DashboardUpdates } from "./dashboard-updates";
import { LayoutGroup, PageLayout } from "./page-layout";
import { DashboardTorrents } from "./dashboard-torrents";
import { appStatusLabel } from "./seedbox-status";
import {
  seedboxSections,
  seedboxSection,
  runtimeLayoutSection,
} from "./seedbox-sections";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  NavLink,
  Link,
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
  Bell,
  CircleAlert,
  CircleCheck,
  Info,
  Download,
  FolderOpen,
  ChevronDown,
  ChevronRight,
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
import { PlatformVersion } from "./platform-version";
import { SidebarClock } from "./sidebar-clock";
import {
  AppRuntimePage,
  DeviceDiagnostics,
  RemoteRuntimeLogs,
  type Runtime,
} from "./runtime";
import {
  IntegrationsCard,
  IntegrationsPage,
  IntegrationAppLinks,
  IntegrationAppCard,
  useIntegrations,
  IntegrationProvider,
  type Integration,
} from "./integrations";
import { CloudflareTunnelCard } from "./cloudflare";
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

import { useData } from "./use-data";
import { batchAppHealthRefresh } from "./app-events";

const SetupWizard = lazy(() =>
  import("./wizard").then((module) => ({ default: module.SetupWizard })),
);
const BackupsPage = lazy(() =>
  import("./backups").then((module) => ({ default: module.BackupsPage })),
);
const UpdatesPage = lazy(() =>
  import("./updates").then((module) => ({ default: module.UpdatesPage })),
);
const SeedboxInstallPage = lazy(() =>
  import("./seedbox-install").then((module) => ({
    default: module.SeedboxInstallPage,
  })),
);
const PlexInstallPage = lazy(() =>
  import("./plex-install").then((module) => ({
    default: module.PlexInstallPage,
  })),
);
const SecuritySettings = lazy(() =>
  import("./security").then((module) => ({ default: module.SecuritySettings })),
);
const AppStorePage = lazy(() =>
  import("./store").then((module) => ({ default: module.AppStorePage })),
);
const CloudflareStorePage = lazy(() =>
  import("./store").then((module) => ({ default: module.CloudflareStorePage })),
);
const FjordHubStorePage = lazy(() =>
  import("./store").then((module) => ({ default: module.FjordHubStorePage })),
);
const WindowsSharePage = lazy(() =>
  import("./windows-share").then((module) => ({
    default: module.WindowsSharePage,
  })),
);
const FjordHubUninstallPage = lazy(() =>
  import("./fjordhub-uninstall").then((module) => ({
    default: module.FjordHubUninstallPage,
  })),
);

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
const simpleDashboard: DashboardSection[] = [
  "storage",
  "torrents",
  "apps",
  "system",
];
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
  "torrents",
];

function Notice({
  children,
  tone = "danger",
}: {
  children: ReactNode;
  tone?: "danger" | "warning" | "info";
}) {
  return (
    <div role="alert" className={`notice ${tone}`}>
      {typeof children === "string" ? t(children) : children}
    </div>
  );
}
function Loading() {
  return (
    <div role="status" className="loading">
      <RefreshCw size={18} className="spin" />
      {t(" Loading MediaHub…")}
    </div>
  );
}
function Badge({ value }: { value: string }) {
  return (
    <span className={`badge ${value}`}>
      <span aria-hidden="true" />
      {t(value)}
    </span>
  );
}
function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="empty">
      <Box size={28} />
      <h3>{t(title)}</h3>
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
        <h2>{t(title)}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Application() {
  useLanguage();
  useAppearanceTheme();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [setupRequired, setSetupRequired] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const refresh = useCallback(async () => {
    try {
      const [status, installation] = await Promise.all([
        api<{ needsSetup: boolean }>("/auth/status"),
        api<{ setup_required: boolean }>("/setup/status"),
      ]);
      setSetupRequired(installation.setup_required);
      setNeedsSetup(status.needsSetup);
      if (!status.needsSetup) {
        try {
          const me = await api<User>("/auth/me");
          setCsrf(me.csrf);
          setLanguage(me.language || "en");
          setAccountAppearance(me.appearance);
          setUser(me);
        } catch {
          setUser(null);
          setAccountAppearance(null);
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
      setLanguage("en");
      setAccountAppearance(null);
    };
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  if (!ready) return <Loading />;
  if (setupRequired)
    return (
      <Suspense fallback={<Loading />}>
        <SetupWizard
          user={user}
          hasAdmin={!needsSetup}
          onSignedIn={(value) => {
            setCsrf(value.csrf);
            setLanguage(value.language || "en");
            setAccountAppearance(value.appearance);
            setUser(value);
            setNeedsSetup(false);
          }}
          onComplete={() => setSetupRequired(false)}
        />
      </Suspense>
    );
  if (!user)
    return (
      <Login
        needsSetup={needsSetup}
        error={connectionError}
        retry={refresh}
        onLogin={(value) => {
          setCsrf(value.csrf);
          setLanguage(value.language || "en");
          setAccountAppearance(value.appearance);
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
        setLanguage("en");
        setAccountAppearance(null);
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
        <span className="eyebrow">{t("YOUR LOCAL CONTROL ROOM")}</span>
        <h1>{needsSetup ? t("A fresh foundation.") : t("Welcome back.")}</h1>
        <p className="muted">
          {needsSetup
            ? t("Create your administrator locally to unlock MediaHub.")
            : t("Sign in to manage your MediaHub.")}
        </p>
        {(error || initialError) && (
          <Notice>{translateText(error) || initialError}</Notice>
        )}
        {needsSetup ? (
          <div className="setup-instructions">
            <p>{t("Run this in the new project’s terminal:")}</p>
            <code>python -m mediahub.cli admin</code>
            <p>
              {t(
                "Your password is entered privately. No default credentials are configured.",
              )}
            </p>
            <button onClick={retry}>
              <RefreshCw size={16} />
              {t(" Check again")}
            </button>
          </div>
        ) : (
          <form onSubmit={submit}>
            <label>
              {t("Username")}
              <input
                autoComplete="username"
                name="username"
                required
                maxLength={80}
              />
            </label>
            <label>
              {t("Password")}
              <input
                autoComplete="current-password"
                type="password"
                name="password"
                required
                maxLength={256}
              />
            </label>
            <label>
              {t("Authenticator or recovery code")}
              <input
                autoComplete="one-time-code"
                name="secondFactor"
                maxLength={32}
                placeholder={t("If two-factor authentication is enabled")}
              />
            </label>
            <button className="primary" disabled={busy}>
              {busy ? t("Signing in…") : t("Sign in")}
              <ArrowUpRight size={17} />
            </button>
          </form>
        )}
        <div className="login-foot">
          <ShieldCheck size={16} />
          {t(" Your private media workspace")}{" "}
          <span>
            {t("v")}
            <PlatformVersion />
          </span>
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
  const navigationIntegrationState = useIntegrations();
  const { items: navigationIntegrations } = navigationIntegrationState;
  const {
    data: navigationApps,
    error: navigationAppsError,
    reload: reloadNavigationApps,
  } = useData<AppInfo[]>("/apps");
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
    source.onopen = () => {
      setLive(true);
      // Live events are not replayed after a restart or temporary disconnect.
      reloadUpdateSummary();
    };
    source.onerror = () => setLive(false);
    source.addEventListener("system.status", (event) => {
      setMetrics(JSON.parse((event as MessageEvent).data));
      setLive(true);
    });
    const appHealth = batchAppHealthRefresh(() => {
      setRevision((n) => n + 1);
      reloadNavigationApps();
    });
    source.addEventListener("app.health.changed", appHealth.changed);
    source.addEventListener("updates.changed", () => reloadUpdateSummary());
    for (const event of [
      "integration.updated",
      "integration.configured",
      "integration.disconnected",
      "integration.removed",
    ]) {
      source.addEventListener(event, () =>
        window.dispatchEvent(new Event("integrations-changed")),
      );
    }
    source.addEventListener("session.expired", () => {
      source.close();
      window.dispatchEvent(new Event("session-expired"));
    });
    return () => {
      appHealth.dispose();
      source.close();
    };
  }, [reloadNavigationApps, reloadUpdateSummary]);
  useEffect(() => {
    const refresh = () => {
      if (!document.hidden) {
        reloadNavigationApps();
        reloadUpdateSummary();
      }
    };
    const timer = window.setInterval(refresh, 10000);
    window.addEventListener("focus", refresh);
    window.addEventListener("apps-changed", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      window.removeEventListener("apps-changed", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [reloadNavigationApps, reloadUpdateSummary]);
  const windowsSharePage = [
    "/apps/windows-share",
    "/store/windows-share",
  ].includes(location.pathname);
  const runtimePage =
    location.pathname.startsWith("/apps/") && !windowsSharePage;
  const storePage = location.pathname.startsWith("/store/");
  const title =
    navigation.find(([path]) => path === location.pathname)?.[1] ||
    (windowsSharePage
      ? "Windows folder access"
      : runtimePage
        ? "App runtime"
        : storePage
          ? "App Store"
          : "Dashboard");
  return (
    <div className="app-shell">
      {open && (
        <button
          className="scrim"
          aria-label={t("Close navigation")}
          onClick={() => setOpen(false)}
        />
      )}
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <Brand />
        <p className="nav-label">{t("WORKSPACE")}</p>
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
                      <span>
                        {typeof label === "string"
                          ? t(label)
                          : translateText(label)}
                      </span>
                    </NavLink>
                    <button
                      type="button"
                      className="nav-expand"
                      aria-label={
                        appsExpanded
                          ? t("Hide app shortcuts")
                          : t("Show app shortcuts")
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
                        .filter(
                          (app) =>
                            app.detailPath &&
                            !app.isMock &&
                            app.packageId !== "org.mediahub.windows-share",
                        )
                        .sort((left, right) =>
                          left.name.localeCompare(right.name),
                        )
                        .map((app) => (
                          <div key={app.id}>
                            <NavLink
                              to={app.detailPath || "/apps"}
                              className="app-shortcut"
                              title={
                                app.packageId === "org.mediahub.windows-share"
                                  ? undefined
                                  : navigationAppsError
                                    ? t("Status unavailable")
                                    : t(app.health.summary || "Unknown")
                              }
                            >
                              <ServiceIcon
                                className="nav-service-icon"
                                packageId={app.packageId}
                                size={20}
                              />
                              <span className="app-shortcut-name">
                                {translateText(app.name)}
                              </span>
                              {app.packageId !==
                                "org.mediahub.windows-share" && (
                                <span
                                  className={`app-shortcut-status ${navigationAppsError ? "unknown" : app.health.status}`}
                                >
                                  <span
                                    aria-hidden="true"
                                    className={`app-shortcut-dot ${navigationAppsError ? "unknown" : app.health.status}`}
                                  />
                                  {t(
                                    appStatusLabel(
                                      navigationAppsError
                                        ? "unknown"
                                        : app.health.status,
                                    ),
                                  )}
                                </span>
                              )}
                            </NavLink>
                            {app.packageId === "org.mediahub.seedbox" &&
                              location.pathname === app.detailPath && (
                                <div className="seedbox-subnav">
                                  {seedboxSections.map(([key, label]) => (
                                    <Link
                                      key={key}
                                      to={`${app.detailPath}?section=${key}`}
                                      className={
                                        seedboxSection(
                                          new URLSearchParams(
                                            location.search,
                                          ).get("section"),
                                        ) === key
                                          ? "active"
                                          : ""
                                      }
                                      aria-current={
                                        seedboxSection(
                                          new URLSearchParams(
                                            location.search,
                                          ).get("section"),
                                        ) === key
                                          ? "page"
                                          : undefined
                                      }
                                    >
                                      {key === "torrents" ? (
                                        <Download size={14} />
                                      ) : key === "vpn" ? (
                                        <ShieldCheck size={14} />
                                      ) : (
                                        <Settings2 size={14} />
                                      )}
                                      {typeof label === "string"
                                        ? t(label)
                                        : translateText(label)}
                                    </Link>
                                  ))}
                                </div>
                              )}
                          </div>
                        ))}
                      {!navigationApps && (
                        <span className="app-shortcuts-loading">
                          {t("Loading apps…")}
                        </span>
                      )}
                      <IntegrationAppLinks items={navigationIntegrations} />
                    </div>
                  )}
                </div>
              ) : path === "/storage" ? (
                <div className="nav-app-group" key={path}>
                  <NavLink to={path}>
                    <Icon size={19} />
                    <span>{t("Storage")}</span>
                  </NavLink>
                  <div className="app-shortcuts storage-shortcuts">
                    <NavLink to="/apps/windows-share" className="app-shortcut">
                      <ServiceIcon
                        className="nav-service-icon"
                        packageId="org.mediahub.windows-share"
                        size={19}
                      />
                      <span className="app-shortcut-name">
                        {t("Windows folder access")}
                      </span>
                    </NavLink>
                  </div>
                </div>
              ) : (
                <NavLink end={path === "/"} key={path} to={path}>
                  <Icon size={19} />
                  <span>
                    {typeof label === "string"
                      ? t(label)
                      : translateText(label)}
                  </span>
                  {path === "/updates" && !!updateSummary?.count && (
                    <span
                      className="nav-update-count"
                      aria-label={t("{value0} updates available", {
                        value0: updateSummary.count,
                      })}
                    >
                      {updateSummary.count > 99 ? "99+" : updateSummary.count}
                    </span>
                  )}
                </NavLink>
              ),
            )}
        </nav>
        <div className="sidebar-bottom">
          <div
            className={`preview-label sidebar-connection ${live ? "healthy" : "unknown"}`}
          >
            <span className={`status-dot ${live ? "healthy" : "unknown"}`} />
            <div>
              {t(live ? "Core online" : "Reconnecting")}
              <small>
                {t("Core uptime")}:{" "}
                {metrics ? uptime(metrics.coreUptimeSeconds) : "—"}
              </small>
            </div>
          </div>
          <div className="profile">
            <span className="avatar">
              {user.username.slice(0, 1).toUpperCase()}
            </span>
            <div>
              {user.username}
              <small>{t("Administrator")}</small>
            </div>
            <button
              className="icon-button"
              title={t("Sign out")}
              aria-label={t("Sign out")}
              onClick={() => {
                onLogout().catch((e) => setError(e.message));
              }}
            >
              <LogOut size={18} />
            </button>
          </div>
          <SidebarClock />
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu icon-button"
              aria-label={open ? t("Close navigation") : t("Open navigation")}
              onClick={() => setOpen(!open)}
            >
              {open ? <X /> : <Menu />}
            </button>
            <span>{displayName}</span>
            <ChevronRight size={15} />
            <strong>{t(title)}</strong>
            <Link className="mobile-brand" to="/" aria-label="MediaHub">
              <Brand />
            </Link>
          </div>
          <div className="topbar-right">
            <WorkspaceSearch
              destinations={[
                ...navigation
                  .filter(
                    ([path]) =>
                      visibleNavigation.includes(path) &&
                      (advancedMode || path !== "/hosts"),
                  )
                  .map(([path, label]) => ({ path, label: t(label) })),
                ...(navigationApps || [])
                  .filter((a) => a.detailPath)
                  .map((a) => ({
                    path: a.detailPath!,
                    label: translateText(a.name),
                  })),
              ]}
            />
            <Badge value={live ? "live" : "reconnecting"} />
            <div className="topbar-actions">
              <Link
                className="topbar-action"
                to="/activity"
                aria-label={t("Notifications")}
                title={t("Notifications")}
              >
                <Bell size={18} />
              </Link>
              <Link
                className="topbar-account"
                to="/settings"
                aria-label={t("Account settings")}
              >
                <span className="avatar topbar-avatar">
                  {user.username.slice(0, 1).toUpperCase()}
                </span>
                <span className="account-copy">
                  <strong>{user.username}</strong>
                  <small>{displayName}</small>
                </span>
              </Link>
            </div>
          </div>
        </header>
        <main className="main-content">
          {!runtimePage && (
            <div className="page-heading">
              <div>
                <span className="eyebrow">
                  {title === "Dashboard" ? t("CONTROL ROOM") : t("WORKSPACE")}
                </span>
                <h1>
                  {title === "Dashboard"
                    ? t("Dashboard")
                    : translateText(title)}
                </h1>
                <p>
                  {title === "Dashboard"
                    ? t("Your media. Your server. Together.")
                    : translateText(pageDescription(title))}
                </p>
              </div>
              {metrics && advancedMode && title !== "Dashboard" && (
                <div className="host-chip">
                  <Server size={17} />
                  <span>
                    {t("MediaHub Core")}
                    <small title={metrics.hostname}>
                      {t("Technical runtime details")}
                    </small>
                  </span>
                </div>
              )}
            </div>
          )}
          {error && <Notice>{translateText(error)}</Notice>}
          {!live && location.pathname !== "/updates" && (
            <Notice tone="warning">
              {t(
                "Live connection interrupted. Reconnecting automatically; displayed metrics may be stale.",
              )}
            </Notice>
          )}
          <PageLayout
            key={`${user.id}:${location.pathname}:${runtimeLayoutSection(new URLSearchParams(location.search).get("section"), !!navigationApps?.some((app) => app.packageId === "org.mediahub.seedbox" && app.detailPath === location.pathname))}`}
            storageKey={`${user.id}:${location.pathname}:${runtimeLayoutSection(new URLSearchParams(location.search).get("section"), !!navigationApps?.some((app) => app.packageId === "org.mediahub.seedbox" && app.detailPath === location.pathname))}`}
          >
            <IntegrationProvider value={navigationIntegrationState}>
              <Suspense fallback={<Loading />}>
                <Routes>
                  <Route
                    path="/apps/install/plex"
                    element={<PlexInstallPage />}
                  />
                  <Route
                    path="/apps/install/seedbox"
                    element={<SeedboxInstallPage />}
                  />
                  <Route
                    path="/apps/:appId/install"
                    element={<SeedboxInstallPage />}
                  />
                  <Route path="/apps/:appId" element={<AppRuntimePage />} />
                  <Route
                    path="/apps/windows-share"
                    element={<WindowsSharePage />}
                  />
                  <Route
                    path="/store/windows-share"
                    element={<WindowsSharePage />}
                  />
                  <Route
                    path="/store/cloudflare"
                    element={<CloudflareStorePage />}
                  />
                  <Route
                    path="/store/fjordhub"
                    element={<FjordHubStorePage />}
                  />
                  <Route
                    path="/store/fjordhub/uninstall"
                    element={<FjordHubUninstallPage />}
                  />
                  <Route path="/store" element={<AppStorePage />} />
                  <Route
                    path="/"
                    element={
                      <Dashboard
                        metrics={metrics}
                        apps={navigationApps}
                        error={navigationAppsError}
                        revision={revision}
                        live={live}
                        sections={dashboardSections}
                      />
                    }
                  />
                  <Route
                    path="/apps"
                    element={
                      <Apps
                        data={navigationApps}
                        error={navigationAppsError}
                        reload={reloadNavigationApps}
                        integrations={navigationIntegrations}
                        extraCards={
                          <section className="store-callout">
                            <div>
                              <strong>{t("Looking for another app?")}</strong>
                              <p>
                                {t(
                                  "Browse guided installations without mixing them into the apps you already run.",
                                )}
                              </p>
                            </div>
                            <NavLink className="primary" to="/store">
                              {t("Open App Store →")}
                            </NavLink>
                          </section>
                        }
                      />
                    }
                  />
                  <Route
                    path="/storage"
                    element={
                      <LayoutGroup id="ui-Shell-2" className="stack">
                        <div
                          className="layout-card"
                          data-layout-title="Media files"
                        >
                          <MediaFiles />
                        </div>
                        <div
                          className="layout-card"
                          data-layout-title="Storage"
                        >
                          <StorageSummary />
                        </div>
                        {advancedMode && (
                          <details className="technical-disclosure">
                            <summary>{t("Technical storage mappings")}</summary>
                            <LayoutGroup id="ui-Shell-3" className="stack">
                              <div
                                className="layout-card"
                                data-layout-title="Storage mappings"
                              >
                                <LogicalStoragePanel />
                              </div>
                              <StorageWorkspace />
                            </LayoutGroup>
                          </details>
                        )}
                      </LayoutGroup>
                    }
                  />
                  <Route path="/hosts" element={<HostsPage />} />
                  <Route path="/integrations" element={<IntegrationsPage />} />
                  <Route
                    path="/activity"
                    element={
                      <LayoutGroup id="activity-cards">
                        <div
                          className="dashboard-card"
                          data-layout-title="Event timeline"
                        >
                          <ActivityPage revision={revision} />
                        </div>
                      </LayoutGroup>
                    }
                  />
                  <Route
                    path="/logs"
                    element={
                      <LayoutGroup id="logs-cards">
                        <div
                          className="dashboard-card"
                          data-layout-title="Logs"
                        >
                          <Logs />
                        </div>
                      </LayoutGroup>
                    }
                  />
                  <Route
                    path="/settings"
                    element={
                      <SettingsExtensions
                        general={
                          <LayoutGroup id="settings-general-layout">
                            <LayoutGroup
                              id="settings-appearance-cards"
                              className="settings-appearance-group stack"
                            >
                              <div
                                className="dashboard-card"
                                data-layout-title="Colors and shades"
                              >
                                <AppearanceSettings />
                              </div>
                            </LayoutGroup>
                            <LayoutGroup id="settings-general-cards">
                              <div
                                className="dashboard-card"
                                data-layout-title="Language"
                              >
                                <LanguageSettings />
                              </div>
                              <div
                                className="dashboard-card"
                                data-layout-title="Workspace preferences"
                              >
                                <SettingsPage />
                              </div>
                            </LayoutGroup>
                          </LayoutGroup>
                        }
                        maintenance={<MaintenancePage />}
                        security={<SecuritySettings />}
                        advanced={advancedMode}
                      />
                    }
                  />
                  <Route
                    path="/updates"
                    element={
                      <UpdatesPage
                        apps={navigationApps}
                        appsError={navigationAppsError}
                      />
                    }
                  />
                  <Route path="/backups" element={<BackupsPage />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Suspense>
            </IntegrationProvider>
          </PageLayout>
          <footer className="footer">
            <span>
              {t("MediaHub Core ")}
              <span className="muted">/</span> {metrics?.version || "…"}
            </span>
            <span>{t("Self-hosted · Your media, your control")}</span>
          </footer>
        </main>
      </div>
      <nav className="mobile-dock" aria-label={t("Quick navigation")}>
        <NavLink to="/" end>
          <LayoutDashboard size={19} />
          <span>{t("Dashboard")}</span>
        </NavLink>
        <NavLink to="/apps">
          <Box size={19} />
          <span>{t("Apps")}</span>
        </NavLink>
        <NavLink to="/storage">
          <HardDrive size={19} />
          <span>{t("Storage")}</span>
        </NavLink>
        <NavLink to="/settings">
          <Settings2 size={19} />
          <span>{t("Settings")}</span>
        </NavLink>
      </nav>
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
      "Windows folder access":
        "Your media folders in Windows Explorer, with guided setup and troubleshooting.",
    } as Record<string, string>
  )[title];
}

function Dashboard({
  metrics: m,
  apps,
  error,
  revision,
  live,
  sections,
}: {
  metrics?: Metrics;
  apps?: AppInfo[];
  error: string;
  revision: number;
  live: boolean;
  sections: DashboardSection[];
}) {
  const {
    data: recentActivity,
    error: activityError,
    reload: reloadActivity,
  } = useData<Activity[]>("/events/history?limit=4");
  useEffect(() => {
    reloadActivity();
  }, [revision, reloadActivity]);
  const reports = useServiceReports(apps);
  const dashboardData = useDashboardData(
    apps?.find((a) => a.packageId === "org.mediahub.seedbox")?.id,
  );
  const samples = useMetricHistory(m);
  if (!m) return <Loading />;
  const visible = new Set(sections);
  const cards: { id: DashboardSection | "updates"; content: ReactNode }[] = [
    { id: "updates", content: <DashboardUpdates /> },
    { id: "storage", content: <StorageSummary /> },
    {
      id: "torrents",
      content: <DashboardTorrents apps={apps} data={dashboardData} />,
    },
    {
      id: "apps",
      content: (
        <Section
          title={t("Your apps")}
          aside={
            <NavLink className="text-link" to="/apps">
              {t("View apps ")}
              <ArrowUpRight size={15} />
            </NavLink>
          }
        >
          <ServiceOverview
            apps={apps}
            reports={reports}
            live={live}
            failed={!!error}
            dashboard={dashboardData}
          />
        </Section>
      ),
    },
    { id: "cloudflare", content: <CloudflareTunnelCard /> },
    { id: "integrations", content: <IntegrationsCard /> },
    {
      id: "activity",
      content: (
        <Section
          title={t("Recent activity")}
          aside={
            <NavLink className="text-link" to="/activity">
              {t("Full timeline ")}
              <ArrowUpRight size={15} />
            </NavLink>
          }
        >
          <ActivityList items={recentActivity || []} />
          {activityError && <Notice>{activityError}</Notice>}
        </Section>
      ),
    },
    {
      id: "network",
      content: (
        <Section title={t("Network throughput")}>
          <div className="network-card">
            <div>
              <ArrowDown size={19} />
              <span>{t("Download")}</span>
              <strong>
                {bytes(m.network.downloadBytesPerSecond)}
                <small>{t("/s")}</small>
              </strong>
            </div>
            <div>
              <ArrowUp size={19} />
              <span>{t("Upload")}</span>
              <strong>
                {bytes(m.network.uploadBytesPerSecond)}
                <small>{t("/s")}</small>
              </strong>
            </div>
          </div>
          <div className="panel-note">
            {t("Runtime network totals, not torrent speeds.")}
          </div>
        </Section>
      ),
    },
    {
      id: "core",
      content: (
        <Section
          title={t("Core status")}
          aside={<Badge value={live ? "healthy" : "unknown"} />}
        >
          <div className="status-rows">
            <StatusLine
              label={t("Backend API")}
              value={live ? "Connected" : "Disconnected"}
            />
            <StatusLine
              label={t("Realtime")}
              value={live ? "Streaming · SSE" : "Reconnecting"}
            />
            <StatusLine
              label={t("Runtime control")}
              value="Agent-verified actions"
            />
            <StatusLine label={t("Public ingress")} value="Not managed" />
            <StatusLine label={t("Release")} value={m.version} />
          </div>
        </Section>
      ),
    },
    { id: "runtime", content: <RuntimePanel /> },
    {
      id: "system",
      content: <ResourceTrends metrics={m} samples={samples} live={live} />,
    },
  ];
  const cardOrder = [
    "apps",
    "system",
    "updates",
    "activity",
    "torrents",
    "storage",
    "network",
    "core",
    "runtime",
    "integrations",
    "cloudflare",
  ];
  return (
    <>
      {error && <Notice>{translateText(error)}</Notice>}
      <div className="dashboard-context">
        <div className="dashboard-status-stack">
          <time dateTime={m.timestamp}>
            {new Date(m.timestamp).toLocaleDateString(getLocale(), {
              weekday: "long",
              day: "numeric",
              month: "long",
              year: "numeric",
            })}
          </time>
          <ControlStatus
            apps={apps}
            live={live}
            failed={!!error}
            reports={reports}
          />
        </div>
        <div className="quick-actions" aria-label={t("Quick actions")}>
          <Link
            to={
              apps?.find((a) => a.packageId === "org.mediahub.seedbox")
                ?.detailPath || "/apps"
            }
          >
            <Download size={15} />
            {t("Downloads")}
          </Link>
          <Link to="/storage">
            <FolderOpen size={15} />
            {t("Media files")}
          </Link>
          <Link to="/updates">
            <RefreshCw size={15} />
            {t("Updates")}
          </Link>
        </div>
      </div>
      <ControlSummary
        metrics={m}
        apps={apps}
        live={live}
        reports={reports}
        appsError={!!error}
        dashboard={dashboardData}
      />
      <LayoutGroup
        id="ui-Dashboard-1"
        className="dashboard-grid"
        defaultHidden={cards
          .filter(({ id }) => id !== "updates" && !visible.has(id))
          .map(({ id }) => id)}
      >
        {cards
          .sort((a, b) => cardOrder.indexOf(a.id) - cardOrder.indexOf(b.id))
          .map(({ id, content }) => (
            <div
              className="dashboard-card"
              key={id}
              data-section={id}
              data-layout-nested={id === "apps" ? "true" : undefined}
              data-layout-title={
                id === "updates"
                  ? "Updates"
                  : dashboardChoices.find((choice) => choice[0] === id)?.[1]
              }
            >
              {content}
            </div>
          ))}
      </LayoutGroup>
    </>
  );
}

function StatusLine({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{typeof label === "string" ? t(label) : translateText(label)}</span>
      <strong>{translateText(value)}</strong>
    </div>
  );
}
function ActivityList({ items }: { items: Activity[] }) {
  return items.length ? (
    <div className="activity-list">
      {items.map((item) => (
        <div className="activity-item" key={item.id}>
          <div className={`activity-icon ${item.severity}`}>
            {item.severity === "error" ||
            item.severity === "critical" ||
            item.severity === "warning" ? (
              <CircleAlert size={15} />
            ) : item.severity === "success" ? (
              <CircleCheck size={15} />
            ) : (
              <Info size={15} />
            )}
          </div>
          <div>
            <strong>{translateText(item.message)}</strong>
            <small>
              {translateText(item.source)} · {translateText(item.severity)}
            </small>
          </div>
          <time dateTime={item.timestamp}>
            {new Date(item.timestamp).toLocaleTimeString(getLocale(), {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </time>
        </div>
      ))}
    </div>
  ) : (
    <Empty title={t("No activity yet")}>
      {t("New events will appear here.")}
    </Empty>
  );
}

export function Apps({
  data,
  error,
  reload,
  integrations,
  extraCards,
}: {
  data?: AppInfo[];
  error: string;
  reload: () => void;
  integrations: Integration[];
  extraCards?: ReactNode;
}) {
  const externalApps = integrations.filter(
    (row) => row.enabled && fjordHubLink(row.baseUrl),
  );
  const [actionError, setError] = useState("");
  const [busy, setBusy] = useState(false);
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
    <LayoutGroup id="ui-Shell-1" className="stack">
      {(error || actionError) && (
        <Notice>{translateText(error) || actionError}</Notice>
      )}
      {!data ? (
        <div
          className="apps-grid app-skeleton-grid"
          aria-busy="true"
          aria-label={t("Loading apps")}
        >
          {[0, 1].map((item) => (
            <div className="panel app-skeleton" key={item}>
              <span />
              <span />
              <span />
            </div>
          ))}
        </div>
      ) : data.length || externalApps.length ? (
        <LayoutGroup id="ui-Apps-1" className="apps-grid">
          {externalApps.map((row) => (
            <IntegrationAppCard
              key={`external-${row.id}`}
              row={row}
              title={row.name}
            />
          ))}
          {[...data]
            .sort((left, right) => left.name.localeCompare(right.name))
            .map((app) => (
              <section className="panel app-detail" key={app.id}>
                <div className="panel-heading">
                  <div className="app-icon">
                    <ServiceIcon packageId={app.packageId} />
                  </div>
                  <Badge value={app.health.status} />
                </div>
                <h2>{translateText(app.name)}</h2>
                <p className="muted">
                  {app.packageId} · {translateText(app.version)}
                </p>
                <p>{translateText(app.health.summary)}</p>
                {app.isMock && (
                  <div className="mock-callout">
                    {t("TEST APP · No real container or media access")}
                  </div>
                )}
                {!app.isMock && (
                  <p className="muted">
                    {app.packageId === "org.mediahub.windows-share"
                      ? t("Installed · Windows setup and connection checks")
                      : app.packageId === "org.mediahub.cloudflared"
                        ? t("Installed · Read-only infrastructure monitor")
                        : t("Installed · Paired Agent runtime")}
                  </p>
                )}
                {app.detailPath && (
                  <NavLink className="text-link" to={app.detailPath}>
                    {t("Open ")}
                    {translateText(app.name)} →
                  </NavLink>
                )}
                {app.isMock && (
                  <div className="button-row">
                    <button
                      disabled={busy || app.state === "running"}
                      onClick={() => act(app.id, "start")}
                    >
                      {t("Start")}
                    </button>
                    <button
                      disabled={busy || app.state === "stopped"}
                      onClick={() => act(app.id, "stop")}
                    >
                      {t("Stop")}
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => act(app.id, "restart")}
                    >
                      {t("Restart")}
                    </button>
                  </div>
                )}
              </section>
            ))}
        </LayoutGroup>
      ) : (
        <Empty title={t("No apps installed")}>
          {t("The app registry is empty.")}
        </Empty>
      )}
      {extraCards}
    </LayoutGroup>
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
      {(error || failure) && <Notice>{translateText(error) || failure}</Notice>}
      {message && (
        <div role="status" className="success">
          {translateText(message)}
        </div>
      )}
      <Section title={t("Storage locations")}>
        {!data ? (
          <Loading />
        ) : !data.length ? (
          <Empty title={t("No locations registered")}>
            {t(
              "Your existing media has not been imported. Register only paths allowed by MEDIAHUB_STORAGE_ROOTS.",
            )}
          </Empty>
        ) : (
          data.map((item) => (
            <div className="storage-row" key={item.id}>
              <HardDrive />
              <div>
                <strong>{item.name}</strong>
                <code>{item.path}</code>
                <small>
                  {translateText(item.kind)}
                  {t(" · Read: ")}
                  {item.readable ? t("yes") : t("no")}
                  {t(" · Write permission: ")}
                  {item.writable ? t("reported") : t("no")}
                </small>
              </div>
              <span>
                {bytes(item.freeBytes)}
                {t(" free")}
              </span>
              <Badge value={item.exists ? "available" : "unavailable"} />
            </div>
          ))
        )}
      </Section>
      <Section title={t("Register existing location")}>
        <form className="storage-form" onSubmit={submit}>
          <label>
            {t("Name")}
            <input name="name" required maxLength={80} />
          </label>
          <label>
            {t("Type")}
            <select name="kind">
              <option value="appdata">{t("App data")}</option>
              <option value="downloads">{t("Downloads")}</option>
              <option value="movies">{t("Movies")}</option>
              <option value="tv">{t("TV shows")}</option>
              <option value="backups">{t("Backups")}</option>
              <option value="custom">{t("Custom")}</option>
            </select>
          </label>
          <label className="wide">
            {t("Absolute path")}
            <input
              name="path"
              required
              placeholder={t("An existing path inside an allowed storage root")}
            />
          </label>
          <p className="muted wide">
            {t(
              "Read-only inspection. Write permission is advisory; no test files are created.",
            )}
          </p>
          <button disabled={busy} className="primary">
            {busy ? t("Checking…") : t("Validate & register")}
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
      title={t("Event timeline")}
      aside={
        <button onClick={reload}>
          <RefreshCw size={15} />
          {t(" Refresh")}
        </button>
      }
    >
      {error && <Notice>{translateText(error)}</Notice>}
      {!data ? (
        <Loading />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("Time")}</th>
                <th>{t("Event / message")}</th>
                <th>{t("Source")}</th>
                <th>{t("Severity")}</th>
              </tr>
            </thead>
            <tbody>
              {data.map((item) => (
                <tr key={item.id}>
                  <td>
                    <time>
                      {new Date(item.timestamp).toLocaleString(getLocale())}
                    </time>
                  </td>
                  <td>
                    <strong>{item.event}</strong>
                    <small>{translateText(item.message)}</small>
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
            <Empty title={t("No events yet")}>
              {t("Activity will appear here.")}
            </Empty>
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
          {t("← Core logs / choose source")}
        </button>
        <RemoteRuntimeLogs appId={source} />
      </div>
    );
  return (
    <Section
      title={t("Core log buffer")}
      aside={
        <button onClick={reload}>
          <RefreshCw size={15} />
          {t(" Refresh")}
        </button>
      }
    >
      <label>
        {t("Log source")}{" "}
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="core">{t("MediaHub Core")}</option>
          {apps
            ?.filter((a) => a.detailPath)
            .map((a) => (
              <option value={a.id} key={a.id}>
                {a.name}
                {t(" Agent / components")}
              </option>
            ))}
        </select>
      </label>
      {error && <Notice>{translateText(error)}</Notice>}
      <div className="log-output">
        {data?.map((log, i) => (
          <div key={i}>
            <time>
              {new Date(log.timestamp).toLocaleTimeString(getLocale())}
            </time>
            <span>{log.level}</span>
            <span>{log.component}</span>
            <p>{translateText(log.message)}</p>
          </div>
        ))}
        {data?.length === 0 && (
          <Empty title={t("No log entries")}>
            {t("Only this Core process is connected.")}
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
      setMessage(t("Your view has been saved."));
      window.dispatchEvent(new Event("settings-changed"));
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Section title={t("Workspace preferences")}>
      {(error || failure) && <Notice>{translateText(error) || failure}</Notice>}
      {message && (
        <div role="status" className="success">
          {translateText(message)}
        </div>
      )}
      {!draft ? (
        <Loading />
      ) : (
        <form className="settings-form" onSubmit={submit}>
          <label>
            {t("Workspace name")}
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
            {t("Appearance")}
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
              <option value="dark">{t("Dark")}</option>
              <option value="light">{t("Light")}</option>
              <option value="system">{t("System")}</option>
            </select>
          </label>
          <label>
            {t("Activity page size")}
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
            {t("GitHub source repository")}
            <input
              name="release_repository"
              value={draft.release_repository || ""}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  release_repository: event.target.value || null,
                })
              }
              placeholder={t("owner/mediahub")}
              pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}"
            />
            <small>
              {t(
                "Public or private repository whose main branch is checked for code changes. Configure encrypted private access on the Updates page.",
              )}
            </small>
          </label>
          <label>
            {t("Automatic update checks")}
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
              <option value={0}>{t("Off")}</option>
              <option value={1}>{t("Every hour")}</option>
              <option value={6}>{t("Every 6 hours")}</option>
              <option value={12}>{t("Every 12 hours")}</option>
              <option value={24}>{t("Every day")}</option>
              <option value={72}>{t("Every 3 days")}</option>
              <option value={168}>{t("Every week")}</option>
            </select>
            <small>
              {t(
                "Checks main for MediaHub code changes and app update metadata. Updates are installed only after explicit approval.",
              )}
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
            {t("Technical mode: show server, network and diagnostic settings")}
          </label>
          <div className="visibility-settings">
            <div className="visibility-heading">
              <div>
                <h3>{t("Choose your menu")}</h3>
                <p>{t("Dashboard and Settings always stay available.")}</p>
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
                  {t("Simple view")}
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
                  {t("Show everything")}
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
                      <strong>
                        {typeof label === "string"
                          ? t(label)
                          : translateText(label)}
                      </strong>
                      <small>{t(navigationHelp[path])}</small>
                    </span>
                  </label>
                );
              })}
            </div>
          </div>
          <div className="visibility-settings">
            <div className="visibility-heading">
              <div>
                <h3>{t("Choose your dashboard")}</h3>
                <p>{t("Only selected cards are shown on the front page.")}</p>
              </div>
              <div className="button-row">
                <button
                  type="button"
                  onClick={() =>
                    setDraft({ ...draft, dashboard_sections: simpleDashboard })
                  }
                >
                  {t("Simple dashboard")}
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
                  {t("All cards")}
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
                    <strong>
                      {typeof label === "string"
                        ? t(label)
                        : translateText(label)}
                    </strong>
                    <small>{t(help)}</small>
                  </span>
                </label>
              ))}
            </div>
          </div>
          <button className="primary" disabled={busy}>
            {busy ? t("Saving…") : t("Save preferences")}
          </button>
          <p className="muted">
            {t(
              "Network, proxy trust and allowed storage roots are configured server-side. Secrets are never returned here.",
            )}
          </p>
        </form>
      )}
    </Section>
  );
}

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
        <h3>{t(title)}</h3>
        <p>{translateText(detail)}</p>
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
          <strong>{t("Seedbox device diagnostics")}</strong>
          <small>
            {t("Disk identity and mount details for troubleshooting only")}
          </small>
        </span>
        <ChevronDown size={17} />
      </summary>
      <div className="maintenance-device-content">
        <div className="runtime-toolbar">
          <p className="muted">
            {t("These technical details stay hidden during normal daily use.")}
          </p>
          <button type="button" onClick={reload}>
            <RefreshCw size={15} />
            {t(" Refresh devices")}
          </button>
        </div>
        {error && <Notice>{translateText(error)}</Notice>}
        {!data && !error && <Loading />}
        {data?.view === "seedbox" && <DeviceDiagnostics report={data.report} />}
      </div>
    </details>
  );
}

function MaintenancePage() {
  const cleanup = useData<{
    state: string;
    message: string;
    reclaimedBytes?: number;
  }>("/maintenance");
  useEffect(() => {
    const timer = window.setInterval(cleanup.reload, 5000);
    return () => window.clearInterval(timer);
  }, [cleanup.reload]);
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
  const appHealth = installedAppsHealth(appsData);
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
      { label: "Clean unused system files", state: "pending" },
    ];
    const details: string[] = [];
    let activeStep = 0;
    const publish = (
      progress: number,
      status: OperationState["status"],
      message: string,
    ) =>
      setOperation({
        title: "Maintenance",
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

      activeStep = 4;
      steps[4].state = "running";
      publish(90, "running", "Cleaning unused system files…");
      const started = await api<{ operationId: string }>(
        "/maintenance",
        "POST",
      );
      let completed = false;
      for (let attempt = 0; attempt < 360; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const result = await api<{
          operationId?: string;
          state: string;
          message: string;
          reclaimedBytes?: number;
        }>("/maintenance");
        if (result.operationId !== started.operationId) continue;
        if (result.state === "failed") throw new Error(result.message);
        if (result.state === "succeeded") {
          details.push(result.message);
          details.push(
            `Freed ${((result.reclaimedBytes || 0) / 1024 ** 3).toLocaleString(getLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false })} GiB of system disk space.`,
          );
          steps[4].state = "complete";
          completed = true;
          break;
        }
      }
      if (!completed)
        throw new Error(
          "Maintenance continues on the host. Reload this page to see its status.",
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
          : "Maintenance and system cleanup completed successfully.",
      );
    } catch (error) {
      steps[activeStep].state = "error";
      details.push(
        "Request failed · see the warning above for the safe error message",
      );
      publish(
        100,
        "error",
        error instanceof Error
          ? error.message
          : "Maintenance could not be completed.",
      );
    } finally {
      setChecking(false);
      core.reload();
      runtime.reload();
      storage.reload();
      apps.reload();
      cleanup.reload();
    }
  };

  return (
    <LayoutGroup id="ui-MaintenancePage-1" className="stack">
      <Section
        title={t("Maintenance")}
        aside={
          <button
            className="maintenance-check"
            type="button"
            onClick={() => void runCheck()}
            disabled={!canRunMaintenance(cleanup.data, cleanup.error, checking)}
          >
            <RefreshCw size={15} className={checking ? "spin" : ""} />
            {checking ? t("Running…") : t("Run maintenance")}
          </button>
        }
      >
        <div className="maintenance-hero">
          <span className="maintenance-hero-icon">
            <Wrench size={24} />
          </span>
          <div>
            <h3>{t("Keep MediaHub healthy")}</h3>
            <p>
              {t(
                "Check the platform, apps and storage, then remove old update files, unused MediaHub images and build cache. Services keep running.",
              )}
            </p>
          </div>
        </div>
        {failure && <Notice>{failure}</Notice>}
        {cleanup.error && <Notice>{translateText(cleanup.error)}</Notice>}
        {cleanup.data && cleanup.data.state !== "idle" && (
          <Notice>{translateText(cleanup.data.message)}</Notice>
        )}
        {operation && <OperationProgress operation={operation} />}
        <div className="maintenance-grid">
          <MaintenanceCard
            icon={<Server size={19} />}
            title={t("MediaHub Core")}
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
            title={t("Agent runtime")}
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
            title={t("Storage")}
            state={storageState}
            detail={
              storageData
                ? `${storageData.filter((item) => item.exists && item.readable).length} of ${storageData.length} locations are available.`
                : "Waiting for the storage health check."
            }
          />
          <MaintenanceCard
            icon={<Box size={19} />}
            title={t("Installed apps")}
            state={appHealth.state}
            detail={appHealth.detail}
          />
        </div>
      </Section>

      <Section title={t("Maintenance tools")}>
        <div className="maintenance-actions">
          <NavLink className="maintenance-action" to="/storage">
            <HardDrive size={20} />
            <span>
              <strong>{t("Storage")}</strong>
              <small>{t("Review capacity, folders and media files")}</small>
            </span>
            <ChevronRight size={17} />
          </NavLink>
          <NavLink className="maintenance-action" to="/updates">
            <RefreshCw size={20} />
            <span>
              <strong>{t("Updates")}</strong>
              <small>{t("Check verified MediaHub and app releases")}</small>
            </span>
            <ChevronRight size={17} />
          </NavLink>
          <NavLink className="maintenance-action" to="/backups">
            <Database size={20} />
            <span>
              <strong>{t("Configuration backups")}</strong>
              <small>{t("Protect settings without duplicating media")}</small>
            </span>
            <ChevronRight size={17} />
          </NavLink>
        </div>
        <div className="maintenance-safety">
          <ShieldCheck size={21} />
          <div>
            <strong>{t("Media stays protected")}</strong>
            <p>
              {t(
                "Movies, TV series, downloads, app data, Docker volumes and rollback backups are preserved. Run maintenance only cleans known disposable update files and unused system build cache. Media folders are never scanned.",
              )}
            </p>
          </div>
        </div>
        {seedboxApp && <SeedboxDeviceMaintenance appId={seedboxApp.id} />}
      </Section>
    </LayoutGroup>
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
    "torrents",
    "Ongoing torrents",
    "Torrent progress, transfer speeds and time remaining",
  ],
  ["system", "System resources", "Live CPU, memory and network measurements"],
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
