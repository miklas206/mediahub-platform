import { usePageSnapshot } from "./use-service-snapshot";
import { StopAppButton } from "./app-controls";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Activity, Search, Settings2 } from "lucide-react";
import { AppUninstall } from "./app-uninstall";
import type { AppInfo, InstalledAppInfo } from "./contracts";
import type { CatalogApp } from "./phase2-types";
import type { Integration } from "./integrations";
import {
  isFjordHubInstalled,
  type FjordHubInstallation,
} from "./fjordhub-status";
import { ServiceIcon } from "./service-icon";
import { appStatusLabel } from "./seedbox-status";
import { t } from "./i18n";
import "./hub-home.css";
import { AppAddressLinks, AppUptime, safeAppUrl } from "./app-uptime";
import { useAppearance, type ThemeStyle, type Appearance } from "./appearance";

export function themedAppUrl(
  path: string,
  packageId: string,
  style: ThemeStyle,
  mode?: Appearance["mode"],
) {
  if (
    ![
      "org.mediahub.seedbox",
      "org.mediahub.mediaseed",
      "org.mediahub.mediavpn",
    ].includes(packageId)
  )
    return path;
  try {
    const url = new URL(path);
    if (!["http:", "https:"].includes(url.protocol)) return path;
    url.searchParams.set("mediahub_theme", style);
    if (mode === "light") url.searchParams.set("mediahub_mode", "light");
    else url.searchParams.delete("mediahub_mode");
    return url.href;
  } catch {
    return path;
  }
}

const hubApps = {
  "org.mediahub.seedbox": {
    name: "MediaSeed",
    description: "Torrents, VPN and automatic feeds.",
    setup: "/store/mediaseed",
    category: "Downloads",
  },
  "org.mediahub.plex": {
    name: "Plex",
    description: "Your media library and streaming server.",
    setup: "/apps/install/plex",
    category: "Media",
  },
  "org.mediahub.jellyfin": {
    name: "Jellyfin",
    description: "Movies, series and music on your own server.",
    setup: "/apps/install/jellyfin",
    category: "Media",
  },
  "org.mediahub.fjordhub": {
    name: "FjordHub",
    description: "Connect FjordHub and manage its own apps from here.",
    setup: "/store/fjordhub",
    category: "Apps",
  },
  "org.mediahub.windows-share": {
    name: "Windows access",
    description: "Open your shared media folders in Windows Explorer.",
    setup: "/store/windows-share",
    category: "Storage",
  },
} as const;

export type HubEntry = {
  id: string;
  name: string;
  description: string;
  category: string;
  path: string;
  configured: boolean;
  status: string;
  statusLabel: string;
  statusDetail?: string;
  action: string;
  external?: boolean;
  settingsPath?: string;
  removableApp?: InstalledAppInfo;
  runtimeAppId?: string;
  canStop?: boolean;
  canStart?: boolean;
  localUrl?: string | null;
  externalUrl?: string | null;
  startedAt?: string | null;
  running?: boolean | null;
  observedAt?: number;
};

export type MediaSeedStatus = {
  configured: boolean;
  available: boolean;
  url: string | null;
  preview?: boolean;
  openUrl?: string | null;
};

/** A catalog entry is a setup option until the live registry confirms it. */
export function buildHubEntries({
  catalog,
  apps,
  appsError = "",
  integrations,
  integrationsError = "",
  deployment,
  deploymentError = "",
  mediaseed,
  mediaseedError = "",
  mediavpn,
  mediavpnError = "",
}: {
  catalog: CatalogApp[];
  apps: AppInfo[] | undefined;
  appsError?: string;
  integrations: Integration[];
  integrationsError?: string;
  deployment: FjordHubInstallation | null | undefined;
  deploymentError?: string;
  mediaseed?: MediaSeedStatus;
  mediaseedError?: string;
  mediavpn?: MediaSeedStatus;
  mediavpnError?: string;
}): HubEntry[] {
  const entries: HubEntry[] = catalog
    .filter(
      (entry) =>
        entry.availability === "available" &&
        ![
          "org.mediahub.windows-share",
          "org.mediahub.cloudflared",
          "org.mediahub.mediavpn",
          "org.mediahub.mediaseed",
        ].includes(entry.id),
    )
    .map((entry) => {
      const definition = hubApps[entry.id as keyof typeof hubApps] || {
        name: entry.name,
        description: entry.description,
        category: entry.category || "Apps",
        setup: "/apps/install/" + entry.id.replace("org.mediahub.", ""),
      };
      if (
        entry.id === "org.mediahub.seedbox" &&
        mediaseed?.configured &&
        mediaseed.url &&
        URL.canParse(mediaseed.url)
      ) {
        const address = new URL(mediaseed.url);
        if (
          ["http:", "https:"].includes(address.protocol) &&
          !address.username &&
          !address.password
        ) {
          return {
            id: entry.id,
            name: "MediaSeed",
            description: "Independent Seedbox app",
            category: definition.category,
            path: mediaseed.openUrl || address.href,
            configured: true,
            external: true,
            status:
              mediaseed.available && !mediaseedError ? "healthy" : "unknown",
            statusLabel: mediaseedError
              ? "Status unavailable"
              : mediaseed.available
                ? "App available"
                : "Check connection",
            action: "Open app",
            settingsPath: "/app-settings/org.mediahub.mediaseed",
            removableApp: apps?.find(
              (app) =>
                app.packageId === "org.mediahub.mediaseed" &&
                !app.isMock &&
                app.removable,
            ),
          };
        }
      }
      const installed = apps?.find(
        (app) =>
          (app.packageId === entry.id ||
            (entry.id === "org.mediahub.seedbox" &&
              app.packageId === "org.mediahub.mediaseed")) &&
          !app.isMock,
      );
      const appAddress =
        safeAppUrl(installed?.externalUrl, installed?.packageId) ||
        safeAppUrl(installed?.localUrl, installed?.packageId);
      const fjordHub = entry.id === "org.mediahub.fjordhub";
      const integration = fjordHub
        ? integrations.find((item) => item.enabled)
        : undefined;
      const deployed = fjordHub && isFjordHubInstalled(deployment);
      const configured = !!installed || !!integration || deployed;
      const statusUnavailable =
        !!appsError ||
        !apps ||
        (fjordHub &&
          (!!integrationsError ||
            (!integration && (!!deploymentError || deployment === undefined))));
      const status = statusUnavailable
        ? "unknown"
        : installed
          ? installed.health.status
          : integration
            ? integration.snapshot.stale
              ? "unknown"
              : integration.snapshot.status === "online"
                ? "healthy"
                : [
                      "degraded",
                      "unhealthy",
                      "offline",
                      "authentication_failed",
                    ].includes(integration.snapshot.status)
                  ? "degraded"
                  : "unknown"
            : "unknown";
      return {
        id: entry.id,
        name: definition.name,
        description: definition.description,
        category: definition.category,
        configured,
        removableApp: installed?.removable ? installed : undefined,
        settingsPath: installed
          ? installed.packageId === "org.mediahub.plex"
            ? installed.detailPath || `/apps/${installed.id}`
            : `/app-settings/${installed.packageId}`
          : undefined,
        external: appAddress ? true : undefined,
        path:
          appAddress ||
          installed?.detailPath ||
          (integration
            ? `/integrations/${encodeURIComponent(integration.id)}`
            : definition.setup),
        status,
        statusLabel: statusUnavailable
          ? "Status unavailable"
          : !configured
            ? "Not set up"
            : installed
              ? appStatusLabel(status)
              : integration
                ? status === "healthy"
                  ? "Connected"
                  : "Check connection"
                : "Complete setup",
        statusDetail: statusUnavailable ? undefined : installed?.health.summary,
        action:
          appAddress || installed?.detailPath || integration
            ? "Open app"
            : deployed
              ? "Complete setup"
              : statusUnavailable
                ? "View setup"
                : "Set up",
      };
    })
    .sort((left, right) => Number(right.configured) - Number(left.configured));
  if (mediavpn?.configured && mediavpn.url && URL.canParse(mediavpn.url)) {
    const address = new URL(mediavpn.url);
    if (
      ["http:", "https:"].includes(address.protocol) &&
      !address.username &&
      !address.password
    ) {
      entries.push({
        id: "org.mediahub.mediavpn",
        name: "MediaVPN",
        description: "WireGuard connections",
        category: "Network",
        path: mediavpn.openUrl || address.href,
        settingsPath: "/app-settings/org.mediahub.mediavpn",
        removableApp: apps?.find(
          (app) =>
            app.packageId === "org.mediahub.mediavpn" &&
            !app.isMock &&
            app.removable,
        ),
        configured: true,
        external: true,
        status: mediavpn.available && !mediavpnError ? "healthy" : "unknown",
        statusLabel: mediavpnError
          ? "Status unavailable"
          : mediavpn.available
            ? "App available"
            : "Check connection",
        action: "Open app",
      });
    }
  }
  if (!entries.some((entry) => entry.id === "org.mediahub.mediavpn")) {
    const installed = apps?.find(
      (app) => app.packageId === "org.mediahub.mediavpn" && !app.isMock,
    );
    const appAddress =
      safeAppUrl(installed?.externalUrl, installed?.packageId) ||
      safeAppUrl(installed?.localUrl, installed?.packageId);
    entries.push({
      id: "org.mediahub.mediavpn",
      name: "MediaVPN",
      description: "WireGuard connections",
      category: "Network",
      path: appAddress || installed?.detailPath || "/store/mediavpn",
      configured: !!installed,
      external: appAddress ? true : undefined,
      removableApp: installed?.removable ? installed : undefined,
      status:
        appsError || mediavpnError
          ? "unknown"
          : installed?.health.status || "unknown",
      statusLabel:
        appsError || mediavpnError
          ? "Status unavailable"
          : installed
            ? appStatusLabel(installed.health.status)
            : "Not set up",
      action: installed ? "Open app" : "Set up",
    });
  }
  return entries
    .map((entry) => {
      const app = apps?.find(
        (row) =>
          !row.isMock &&
          (row.packageId === entry.id ||
            (entry.id === "org.mediahub.seedbox" &&
              row.packageId === "org.mediahub.mediaseed")),
      );
      const separate =
        entry.id === "org.mediahub.seedbox"
          ? mediaseed
          : entry.id === "org.mediahub.mediavpn"
            ? mediavpn
            : undefined;
      const integration =
        entry.id === "org.mediahub.fjordhub"
          ? integrations.find((row) => row.enabled)
          : undefined;
      return {
        ...entry,
        settingsPath:
          entry.settingsPath ||
          (entry.configured
            ? `/app-settings/${app?.packageId || entry.id}`
            : undefined),
        localUrl: app?.localUrl || separate?.url || integration?.baseUrl,
        externalUrl: app?.externalUrl,
        runtimeAppId: app?.id,
        canStop: app?.controls?.actions.includes("stop"),
        canStart: app?.controls?.actions.includes("start"),
        ...(!appsError &&
        app?.running === false &&
        (app.observedAt == null || Date.now() / 1000 - app.observedAt <= 30)
          ? {
              status: "stopped",
              statusLabel: "Not running",
              statusDetail: "Start the app to use it.",
            }
          : {}),
        running: app?.running,
        startedAt: app?.startedAt,
        observedAt: app?.observedAt,
      };
    })
    .sort((left, right) => Number(right.configured) - Number(left.configured));
}

export function HubHome({
  apps,
  appsError,
  integrations,
  integrationsError,
  live,
}: {
  apps: AppInfo[] | undefined;
  appsError: string;
  integrations: Integration[];
  integrationsError: string;
  updates: number | undefined;
  live: boolean;
}) {
  const appearance = useAppearance();
  const onAppRemoved = useCallback(() => {
    window.dispatchEvent(new Event("apps-changed"));
  }, []);
  const catalog = usePageSnapshot<CatalogApp[]>("/catalog");
  const deployment = usePageSnapshot<FjordHubInstallation | null>(
    "/fjordhub/deployment",
  );
  const mediaseed = usePageSnapshot<MediaSeedStatus>("/mediaseed/status");
  const mediavpn = usePageSnapshot<MediaSeedStatus>("/mediavpn/status");
  const reloadDeployment = deployment.reload;
  const reloadMediaSeed = mediaseed.reload;
  const reloadMediaVPN = mediavpn.reload;
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  useEffect(() => {
    const refresh = () => {
      reloadDeployment();
      reloadMediaSeed();
      reloadMediaVPN();
    };
    window.addEventListener("apps-changed", refresh);
    window.addEventListener("integrations-changed", refresh);
    return () => {
      window.removeEventListener("apps-changed", refresh);
      window.removeEventListener("integrations-changed", refresh);
    };
  }, [reloadDeployment, reloadMediaSeed, reloadMediaVPN]);
  const entries = buildHubEntries({
    catalog: catalog.data || [],
    apps,
    appsError: appsError || (!live ? t("Reconnecting") : ""),
    integrations,
    integrationsError,
    deployment: deployment.data,
    deploymentError: deployment.error,
    mediaseed: mediaseed.data,
    mediaseedError: mediaseed.error,
    mediavpn: mediavpn.data,
    mediavpnError: mediavpn.error,
  });
  const cards: HubEntry[] = [
    ...entries,
    {
      id: "healthcheck",
      name: "Healthcheck",
      description: "Health checks, diagnostics and safe maintenance.",
      category: "MediaHub",
      path: "/maintenance",
      configured: true,
      status: "builtin",
      statusLabel: "Built in",
      action: "Open healthcheck",
    },
  ];
  const visible = cards.filter(
    (entry) =>
      (filter === "all" ||
        (filter === "running"
          ? entry.configured && entry.status === "healthy"
          : filter === "setup"
            ? !entry.configured
            : entry.category === filter)) &&
      [entry.name, t(entry.name), t(entry.description), t(entry.category)]
        .join(" ")
        .toLocaleLowerCase()
        .includes(query.trim().toLocaleLowerCase()),
  );
  const error =
    catalog.error || appsError || integrationsError || deployment.error;
  return (
    <div className="hub-home">
      <header className="reference-page-title">
        <h1>{t("Apps & Services")}</h1>
        <p>{t("Install, configure and manage your media stack.")}</p>
      </header>
      <section className="hub-app-section" aria-label={t("Apps & Services")}>
        <label className="hub-search">
          <Search size={17} />
          <span className="sr-only">{t("Find an app")}</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("Search apps...")}
            type="search"
          />
        </label>
        <div className="hub-filters" role="group" aria-label={t("Filter apps")}>
          {[
            ["all", "All apps"],
            ["running", "Running"],
            ["setup", "Available to set up"],
            ["Media", "Media"],
            ["Downloads", "Downloads"],
            ["Network", "Network"],
          ].map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={filter === key ? "selected" : ""}
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
            >
              {t(label)}
              <span>
                {
                  cards.filter(
                    (entry) =>
                      key === "all" ||
                      (key === "running"
                        ? entry.configured && entry.status === "healthy"
                        : key === "setup"
                          ? !entry.configured
                          : entry.category === key),
                  ).length
                }
              </span>
            </button>
          ))}
        </div>
        {error && (
          <div className="notice warning" role="alert">
            <span>
              {t(
                "Some app information could not be refreshed. Status may be unavailable.",
              )}
            </span>
            <button
              type="button"
              onClick={() => {
                catalog.reload();
                deployment.reload();
                mediaseed.reload();
                mediavpn.reload();
                window.dispatchEvent(new Event("apps-changed"));
                window.dispatchEvent(new Event("integrations-changed"));
              }}
            >
              {t("Retry")}
            </button>
          </div>
        )}
        {!catalog.data && !catalog.error ? (
          <div
            className="hub-app-grid"
            aria-busy="true"
            aria-label={t("Loading apps…")}
          >
            {[0, 1, 2, 3, 4, 5].map((id) => (
              <div className="hub-app-skeleton" key={id}>
                <span />
                <span />
                <span />
              </div>
            ))}
          </div>
        ) : (
          <div className="hub-app-grid reference-app-grid">
            {visible.map((entry) => (
              <article
                className={`hub-app-card ${entry.configured ? "configured" : "setup"}`}
                key={entry.id}
                data-app-id={entry.id}
              >
                <div className="hub-card-main">
                  <span className="hub-app-icon">
                    {entry.id === "healthcheck" ? (
                      <Activity size={29} />
                    ) : (
                      <ServiceIcon packageId={entry.id} size={32} />
                    )}
                  </span>
                  <div className="hub-card-copy">
                    <h3>{t(entry.name)}</h3>
                    <span
                      className={`hub-app-status ${entry.status}`}
                      title={
                        entry.statusDetail ? t(entry.statusDetail) : undefined
                      }
                    >
                      <span />
                      {t(entry.statusLabel)}
                    </span>
                  </div>
                </div>
                <p className="hub-card-description">{t(entry.description)}</p>
                {entry.configured && entry.id !== "healthcheck" && (
                  <div className="hub-card-runtime">
                    <AppAddressLinks
                      localUrl={entry.localUrl}
                      externalUrl={entry.externalUrl}
                      packageId={entry.id}
                    />
                    <AppUptime
                      startedAt={entry.startedAt}
                      running={entry.running}
                      observedAt={entry.observedAt}
                    />
                  </div>
                )}
                <div className="hub-card-footer">
                  {entry.external ? (
                    <a
                      className="hub-card-action"
                      href={themedAppUrl(
                        entry.path,
                        entry.id,
                        appearance?.style || "midnight-glass",
                        appearance?.mode,
                      )}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`${t(entry.action)} · ${t(entry.name)}`}
                    >
                      {t(entry.action)}
                    </a>
                  ) : (
                    <Link
                      className="hub-card-action"
                      to={entry.path}
                      aria-label={`${t(entry.action)} · ${t(entry.name)}`}
                    >
                      {t(entry.action)}
                    </Link>
                  )}
                  {(entry.running === false ? entry.canStart : entry.canStop) &&
                    entry.runtimeAppId && (
                      <StopAppButton
                        appId={entry.runtimeAppId}
                        name={entry.name}
                        packageId={
                          entry.id === "org.mediahub.seedbox"
                            ? "org.mediahub.mediaseed"
                            : entry.id
                        }
                        running={entry.running}
                        onChanged={onAppRemoved}
                      />
                    )}
                  {entry.settingsPath && (
                    <Link
                      className="hub-card-settings"
                      to={entry.settingsPath}
                      title={`${t("Settings")}: ${entry.name}`}
                      aria-label={`${t("Settings")}: ${entry.name}`}
                    >
                      <Settings2 size={16} />
                    </Link>
                  )}
                </div>
                {entry.removableApp && (
                  <AppUninstall
                    app={entry.removableApp}
                    onRemoved={onAppRemoved}
                    buttonClassName="hub-card-uninstall"
                    showIcon
                  />
                )}
              </article>
            ))}
          </div>
        )}
        {!!catalog.data && !visible.length && (
          <div className="hub-empty">
            <Search size={24} />
            <h3>{t("No matching apps")}</h3>
            <p>{t("Try another search or show all apps.")}</p>
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setFilter("all");
              }}
            >
              {t("Show all apps")}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
