import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  Box,
  RefreshCw,
  Search,
} from "lucide-react";
import type { AppInfo } from "./contracts";
import type { CatalogApp } from "./phase2-types";
import type { Integration } from "./integrations";
import {
  isFjordHubInstalled,
  type FjordHubInstallation,
} from "./fjordhub-status";
import { ServiceIcon } from "./service-icon";
import { appStatusLabel } from "./seedbox-status";
import { t } from "./i18n";
import { useData } from "./use-data";
import "./hub-home.css";

const hubApps = {
  "org.mediahub.seedbox": {
    name: "Seedbox",
    description: "Torrents, VPN and automatic feeds.",
    setup: "/apps/install/seedbox",
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
  "org.mediahub.cloudflared": {
    name: "Cloudflare",
    description: "Tunnel connections, public routes and monitoring.",
    setup: "/store/cloudflare",
    category: "Network",
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
}: {
  catalog: CatalogApp[];
  apps: AppInfo[] | undefined;
  appsError?: string;
  integrations: Integration[];
  integrationsError?: string;
  deployment: FjordHubInstallation | null | undefined;
  deploymentError?: string;
}): HubEntry[] {
  return catalog
    .filter(
      (entry) =>
        entry.availability === "available" && Object.hasOwn(hubApps, entry.id),
    )
    .map((entry) => {
      const definition = hubApps[entry.id as keyof typeof hubApps];
      const installed = apps?.find(
        (app) => app.packageId === entry.id && !app.isMock,
      );
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
        path:
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
          installed?.detailPath || integration
            ? "Open app"
            : deployed
              ? "Complete setup"
              : statusUnavailable
                ? "View setup"
                : "Set up",
      };
    })
    .sort((left, right) => Number(right.configured) - Number(left.configured));
}

export function HubHome({
  apps,
  appsError,
  integrations,
  integrationsError,
  updates,
  live,
}: {
  apps: AppInfo[] | undefined;
  appsError: string;
  integrations: Integration[];
  integrationsError: string;
  updates: number | undefined;
  live: boolean;
}) {
  const catalog = useData<CatalogApp[]>("/catalog");
  const deployment = useData<FjordHubInstallation | null>(
    "/fjordhub/deployment",
  );
  const reloadDeployment = deployment.reload;
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "configured" | "setup">("all");
  useEffect(() => {
    const refresh = () => reloadDeployment();
    window.addEventListener("apps-changed", refresh);
    window.addEventListener("integrations-changed", refresh);
    return () => {
      window.removeEventListener("apps-changed", refresh);
      window.removeEventListener("integrations-changed", refresh);
    };
  }, [reloadDeployment]);
  const entries = buildHubEntries({
    catalog: catalog.data || [],
    apps,
    appsError,
    integrations,
    integrationsError,
    deployment: deployment.data,
    deploymentError: deployment.error,
  });
  const configured = entries.filter((entry) => entry.configured).length;
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
        (filter === "configured" ? entry.configured : !entry.configured)) &&
      [entry.name, t(entry.name), t(entry.description), t(entry.category)]
        .join(" ")
        .toLocaleLowerCase()
        .includes(query.trim().toLocaleLowerCase()),
  );
  const error =
    catalog.error || appsError || integrationsError || deployment.error;
  return (
    <div className="hub-home">
      <header className="hub-heading">
        <div>
          <p className="eyebrow">{t("YOUR APP HUB")}</p>
          <h1>
            MediaHub <span className="hub-beta">beta</span>
          </h1>
          <p>{t("Your apps, media and services. Together in one place.")}</p>
        </div>
      </header>
      <div className="hub-status-strip" aria-label={t("Hub status")}>
        <span>
          <span className={`status-dot ${live ? "healthy" : "unknown"}`} />
          {t(live ? "Hub connected" : "Reconnecting")}
        </span>
        <span>
          <Box size={15} />
          {apps && !appsError
            ? t("{count} configured apps", { count: configured })
            : t("Checking apps")}
        </span>
        <Link to="/updates">
          <RefreshCw size={15} />
          {updates === undefined
            ? t("Check updates")
            : updates
              ? t("{count} updates available", { count: updates })
              : t("Updates")}
          <ArrowRight size={14} />
        </Link>
      </div>
      <section className="hub-app-section" aria-labelledby="hub-apps-heading">
        <div className="hub-app-toolbar">
          <div>
            <h2 id="hub-apps-heading">{t("Your apps")}</h2>
            <p>{t("Open an app or choose one to set up.")}</p>
          </div>
          <label className="hub-search">
            <Search size={17} />
            <span className="sr-only">{t("Find an app")}</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("Find an app")}
              type="search"
            />
          </label>
        </div>
        <div className="hub-filters" role="group" aria-label={t("Filter apps")}>
          {(
            [
              ["all", "All apps"],
              ["configured", "Ready to open"],
              ["setup", "Available to set up"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={filter === key ? "selected" : ""}
              aria-pressed={filter === key}
              onClick={() => setFilter(key)}
            >
              {t(label)}
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
          <div className="hub-app-groups">
            {[true, false].map((isConfigured) => {
              const group = visible.filter(
                (entry) => entry.configured === isConfigured,
              );
              if (!group.length) return null;
              return (
                <section
                  key={String(isConfigured)}
                  aria-labelledby={`hub-group-${isConfigured}`}
                >
                  <h3
                    className="hub-group-heading"
                    id={`hub-group-${isConfigured}`}
                  >
                    {t(isConfigured ? "Added apps" : "Available to set up")}
                    <span>{group.length}</span>
                  </h3>
                  <div className="hub-app-grid">
                    {group.map((entry) => (
                      <article
                        className={`hub-app-card ${entry.configured ? "configured" : "setup"}`}
                        key={entry.id}
                        data-app-id={entry.id}
                      >
                        <div className="hub-card-top">
                          <span
                            className={`hub-app-icon ${entry.id === "healthcheck" ? "healthcheck" : ""}`}
                          >
                            {entry.id === "healthcheck" ? (
                              <Activity size={29} />
                            ) : (
                              <ServiceIcon packageId={entry.id} size={32} />
                            )}
                          </span>
                          <span
                            className={`hub-app-status ${entry.status}`}
                            title={
                              entry.statusDetail
                                ? t(entry.statusDetail)
                                : undefined
                            }
                          >
                            <span />
                            {t(entry.statusLabel)}
                          </span>
                        </div>
                        <div className="hub-card-copy">
                          <span className="hub-app-category">
                            {t(entry.category)}
                          </span>
                          <h3>{t(entry.name)}</h3>
                          <p>{t(entry.description)}</p>
                        </div>
                        <Link
                          className="hub-card-action"
                          to={entry.path}
                          aria-label={`${t(entry.action)} · ${t(entry.name)}`}
                        >
                          <span>{t(entry.action)}</span>
                          <ArrowRight size={17} />
                        </Link>
                      </article>
                    ))}
                  </div>
                </section>
              );
            })}
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
