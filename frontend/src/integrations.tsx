import { getLocale, translateText, t } from "./i18n";

import { LayoutGroup } from "./page-layout";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { bytes } from "./format";
import { ErrorBox, Panel } from "./phase2";
import "./integrations.css";
import { FjordHubTokenGuide, fjordHubLink } from "./fjordhub-token-guide";
import { ServiceIcon } from "./service-icon";
import { ArrowUpRight } from "lucide-react";

type Row = Record<string, string | number>;
type Snapshot = {
  status: string;
  version?: string;
  api_version?: string;
  capabilities?: string[];
  failed_endpoint?: string;
  stale?: boolean;
  apps?: Row[];
  storage?: Row[];
  metrics?: Record<string, number>;
  events?: Row[];
  warnings?: string[];
};
export type Integration = {
  id: string;
  name: string;
  baseUrl: string;
  allowHttp: boolean;
  tokenConfigured: boolean;
  enabled: boolean;
  snapshot: Snapshot;
  lastSuccessfulSync: string | null;
  nextSync: number;
};
const statusLabels: Record<string, string> = {
  detected: "Installed · Access Token required",
  pending_setup: "Installed · Complete administrator setup in FjordHub",
  online: "Connected",
  degraded: "Degraded",
  offline: "FjordHub offline",
  timeout: "Connection timed out",
  authentication_failed: "Authentication failed",
  missing_scope: "Insufficient scope / permission",
  lan_access_denied: "Access denied — FjordHub requires a local LAN connection",
  api_incompatible: "Unsupported API version or endpoint",
  invalid_response: "Invalid API response",
  rate_limited: "Rate limited — respecting Retry-After",
  not_checked: "Not checked yet",
  disconnected: "Disconnected",
  credentials_unavailable: "Stored Access Token unavailable",
  unhealthy: "FjordHub reports unhealthy",
};
const label = (s: string) => t(statusLabels[s] || s);

export function useIntegrations() {
  const request = useRef<AbortController | null>(null);
  const [items, setItems] = useState<Integration[]>([]),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    try {
      const items = await api<Integration[]>(
        "/integrations",
        "GET",
        undefined,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setItems(items);
        setError("");
      }
    } catch (e) {
      if (!controller.signal.aborted) setError((e as Error).message);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload();
    const timer = setInterval(() => void reload(), 15000);
    const refresh = () => void reload();
    window.addEventListener("integrations-changed", refresh);
    return () => {
      clearInterval(timer);
      window.removeEventListener("integrations-changed", refresh);
      request.current?.abort();
    };
  }, [reload]);
  return { items, error, loading, reload };
}

export function installedFjordHubApps(row: Integration) {
  if (
    !row.enabled ||
    !row.tokenConfigured ||
    !row.snapshot.capabilities?.includes("docker.resources.read")
  )
    return [];
  return (row.snapshot.apps || []).filter(
    (app) =>
      /^[a-zA-Z0-9_-]{1,100}$/.test(String(app.id)) &&
      Number(app.container_count) > 0,
  );
}

export function IntegrationAppCard({
  row,
  title,
}: {
  row: Integration;
  title: string;
}) {
  const href = fjordHubLink(row.baseUrl);
  if (!row.enabled || !href) return null;
  return (
    <section className="panel app-detail" aria-label={title}>
      <div className="panel-heading">
        <div className="app-icon">
          <ServiceIcon packageId="org.mediahub.fjordhub" />
        </div>
        <span
          className={`badge ${!row.snapshot.stale && row.snapshot.status === "online" ? "healthy" : row.snapshot.status === "degraded" ? "degraded" : "unknown"}`}
        >
          {label(row.snapshot.status)}
        </span>
      </div>
      <h2>{row.name}</h2>
      <p className="muted">
        {row.tokenConfigured
          ? t("Installed · Read-only integration")
          : t("Installed · Access Token required")}
      </p>
      <a
        className="text-link"
        href={href}
        target="_blank"
        rel="noopener noreferrer"
      >
        {t("Open ")}
        {row.name} →
      </a>
      <div className="stack">
        {installedFjordHubApps(row).map((app) => (
          <a
            key={String(app.id)}
            className="text-link"
            href={`${href}/#card-${encodeURIComponent(String(app.id))}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            {String(app.name)} · {Number(app.running_count)}/
            {Number(app.container_count)} {t("running")}
          </a>
        ))}
      </div>
    </section>
  );
}

export function IntegrationAppLinks({ items }: { items: Integration[] }) {
  return (
    <>
      {items
        .filter((row) => row.enabled)
        .map((row) => {
          const href = fjordHubLink(row.baseUrl);
          if (!href) return null;
          const healthy =
            row.snapshot.status === "online" && !row.snapshot.stale;
          return (
            <div key={row.id} className="fjordhub-app-navigation">
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                title={t("Open {value0} · {value1}", {
                  value0: row.name,
                  value1: href,
                })}
              >
                <ServiceIcon packageId="org.mediahub.fjordhub" size={18} />
                <span
                  className={`app-shortcut-dot ${healthy ? "healthy" : "unknown"}`}
                />
                <span>{row.name}</span>
                <ArrowUpRight size={13} aria-hidden="true" />
              </a>
              <div className="app-subnav">
                {installedFjordHubApps(row).map((app) => (
                  <a
                    key={String(app.id)}
                    href={`${href}/#card-${encodeURIComponent(String(app.id))}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <ServiceIcon packageId={String(app.id)} size={16} />
                    <span>{String(app.name)}</span>
                    <span
                      className={`app-shortcut-dot ${!row.snapshot.stale && Number(app.running_count) > 0 ? "healthy" : "unknown"}`}
                    />
                  </a>
                ))}
              </div>
            </div>
          );
        })}
    </>
  );
}

export function IntegrationsCard() {
  const { items, error, loading } = useIntegrations();
  return (
    <Panel title={t("External integrations")}>
      <ErrorBox error={error} />
      {loading ? (
        <p role="status">{t("Loading integrations…")}</p>
      ) : !items.length ? (
        <p>
          {t(
            "No external integrations configured. MediaHub works independently.",
          )}
        </p>
      ) : (
        items.map((row) => (
          <div className="app-row" key={row.id}>
            <div className="app-row-name">
              <strong>{row.name}</strong>
              <small>
                {label(row.snapshot.status)} ·{" "}
                {(row.snapshot.apps || []).length}{" "}
                {row.snapshot.capabilities?.includes("docker.resources.read")
                  ? t("app groups")
                  : t("catalog entries")}
              </small>
            </div>
            <Link to="/integrations">{t("View")}</Link>
          </div>
        ))
      )}
      <Link className="text-link" to="/integrations">
        {t("Manage FjordHub integration →")}
      </Link>
    </Panel>
  );
}

export function IntegrationsPage({
  onUrlChange,
  showTokenGuide = true,
}: {
  onUrlChange?: (url: string) => void;
  showTokenGuide?: boolean;
} = {}) {
  const { items, error, loading, reload } = useIntegrations();
  const [name, setName] = useState("FjordHub"),
    [baseUrl, setUrl] = useState(""),
    [token, setToken] = useState(""),
    [allowHttp, setHttp] = useState(false);
  const [busy, setBusy] = useState(false),
    [failure, setFailure] = useState(""),
    [test, setTest] = useState<Snapshot | null>(null),
    [notice, setNotice] = useState("");
  useEffect(() => {
    onUrlChange?.(baseUrl);
  }, [baseUrl, onUrlChange]);
  useEffect(() => {
    void api<{ baseUrl: string | null }>("/integrations/fjordhub/defaults")
      .then((value) => {
        if (value.baseUrl) setUrl((current) => current || value.baseUrl!);
      })
      .catch(() => {});
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    await act("save");
  }
  async function act(action: "save" | "test") {
    setBusy(true);
    setFailure("");
    setNotice("");
    try {
      const body = { name, baseUrl, accessToken: token, allowHttp };
      if (action === "test")
        setTest(
          await api<Snapshot>("/integrations/fjordhub/test", "POST", body),
        );
      else {
        await api("/integrations/fjordhub", "POST", body);
        setToken("");
        setTest(null);
        setNotice("Saved securely. Access Token will not be displayed again.");
        await reload();
        window.dispatchEvent(new Event("integrations-changed"));
      }
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function detect() {
    setBusy(true);
    setFailure("");
    try {
      await api("/integrations/fjordhub/detect", "POST", {
        name,
        baseUrl,
        allowHttp,
      });
      setNotice(
        "FjordHub detected. Add an Access Token to show its installed apps.",
      );
      await reload();
      window.dispatchEvent(new Event("integrations-changed"));
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function manage(id: string, action: "refresh" | "disconnect") {
    setBusy(true);
    setFailure("");
    try {
      await api(`/integrations/${id}/${action}`, "POST", {});
      await reload();
      window.dispatchEvent(new Event("integrations-changed"));
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <LayoutGroup
      id="integrations-IntegrationsPage-1"
      className="stack integrations-page"
    >
      <div>
        <p className="muted">
          {t(
            "Read-only external services. Separate from managed hosts and apps.",
          )}
        </p>
      </div>
      <ErrorBox error={error || failure} />
      {notice && <p role="status">{translateText(notice)}</p>}
      <Panel title={t("Connect FjordHub")}>
        <form onSubmit={submit} className="stack">
          <label>
            {t("Display name")}
            <input
              required
              maxLength={80}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            {t("FjordHub URL")}
            <input
              required
              type="url"
              value={baseUrl}
              placeholder={t("http://your-fjordhub-lan-ip:port")}
              onChange={(e) => {
                setUrl(e.target.value);
                setTest(null);
              }}
            />
          </label>
          <p className="muted">
            {t(
              "Enter FjordHub’s normal local URL, without an API path. MediaHub adds the supported read-only route automatically. Current FjordHub versions expose Docker resource usage; older versions may expose only a catalog. Public Cloudflare access cannot be used for this LAN-only endpoint.",
            )}
          </p>
          {showTokenGuide && <FjordHubTokenGuide baseUrl={baseUrl} />}
          <label>
            {t("Access Token")}
            <input
              required
              type="password"
              autoComplete="new-password"
              minLength={16}
              maxLength={8192}
              value={token}
              onChange={(e) => {
                setToken(e.target.value);
                setTest(null);
              }}
            />
          </label>
          <label className="integration-consent">
            <input
              type="checkbox"
              checked={allowHttp}
              onChange={(e) => setHttp(e.target.checked)}
            />{" "}
            {t("Allow HTTP to this LAN-only FjordHub API")}
          </label>
          {allowHttp && (
            <p role="note">
              {t(
                "The Access Token is not encrypted between Core and an HTTP API. Prefer verified HTTPS. Browser submission to MediaHub still requires HTTPS.",
              )}
            </p>
          )}
          <div className="button-row">
            <button
              type="button"
              disabled={busy || !baseUrl}
              onClick={() => void detect()}
            >
              {t("Detect existing FjordHub")}
            </button>
            <button
              type="button"
              disabled={busy || token.length < 16 || !baseUrl}
              onClick={() => void act("test")}
            >
              {t("Test Connection")}
            </button>
            <button type="submit" disabled={busy || token.length < 16}>
              {busy ? t("Working…") : t("Save")}
            </button>
          </div>
          {test && (
            <div role="status">
              <strong>{label(test.status)}</strong>
              <p>
                {t("FjordHub ")}
                {test.version || t("version unavailable")}
                {t(" · API")} {test.api_version || t("not verified")}
              </p>
              {test.status === "online" && (
                <p>
                  {test.apps?.length ?? 0}
                  {t(" entries found · Capabilities:")}{" "}
                  {test.capabilities?.join(", ")}
                  {t(" · Read-only integration")}
                </p>
              )}
              {test.failed_endpoint && (
                <p>
                  {t("Endpoint requiring attention: ")}
                  {test.failed_endpoint}
                </p>
              )}
            </div>
          )}
        </form>
      </Panel>
      {loading && <p role="status">{t("Loading configured integrations…")}</p>}
      {!loading && !items.length && (
        <Panel title={t("No integrations yet")}>
          <p>
            {t(
              "Add FjordHub above. It is optional and cannot affect Core health.",
            )}
          </p>
        </Panel>
      )}
      {items.map((row) => (
        <Panel key={row.id} title={row.name}>
          <div className="stack integration-details">
            <div>
              <strong>{label(row.snapshot.status)}</strong>
              <p className="muted">{row.baseUrl}</p>
            </div>
            {row.snapshot.stale && (
              <p role="status">
                {t(
                  "Showing the last successful snapshot; these values are not live.",
                )}
              </p>
            )}
            {row.snapshot.failed_endpoint && (
              <p>
                {t("Endpoint requiring attention: ")}
                {row.snapshot.failed_endpoint}
              </p>
            )}
            <dl>
              <dt>{t("Access Token")}</dt>
              <dd>
                {row.tokenConfigured ? t("Configured") : t("Not configured")}
              </dd>
              <dt>{t("Last successful sync")}</dt>
              <dd>
                {row.lastSuccessfulSync
                  ? new Date(row.lastSuccessfulSync).toLocaleString(getLocale())
                  : t("Not yet verified")}
              </dd>
              <dt>{t("Version")}</dt>
              <dd>{row.snapshot.version || t("Unavailable")}</dd>
              <dt>{t("API version")}</dt>
              <dd>{row.snapshot.api_version || t("Unverified")}</dd>
            </dl>
            <div className="button-row">
              <button
                disabled={busy || !row.enabled}
                onClick={() => void manage(row.id, "refresh")}
              >
                {t("Refresh")}
              </button>
              <button
                disabled={busy || !row.enabled}
                onClick={() => void manage(row.id, "disconnect")}
              >
                {t("Disconnect")}
              </button>
            </div>
            <small className="muted">
              {row.enabled &&
              row.snapshot.capabilities?.includes("docker.resources.read")
                ? row.snapshot.stale
                  ? t(
                      "Connection interrupted. Showing the last measurements while retrying automatically.",
                    )
                  : t("Live resource updates approximately every 5 seconds.")
                : t("Status updates automatically.")}{" "}
              {t("Provider retry delays are respected.")}
            </small>
            {(row.snapshot.warnings || []).map((warning, i) => (
              <p role="note" key={i}>
                {translateText(warning)}
              </p>
            ))}
            <h3>
              {row.snapshot.capabilities?.includes("docker.resources.read")
                ? t("Installed app groups")
                : t("Installable app catalog")}
            </h3>
            {!row.snapshot.apps?.length ? (
              <p>{t("No apps reported by the API.")}</p>
            ) : (
              row.snapshot.apps.map((app, i) => (
                <div className="app-row" key={String(app.id ?? i)}>
                  <div className="app-row-name">
                    <strong>{app.name || app.id || t("Unnamed app")}</strong>
                    <small>
                      {app.running_count !== undefined
                        ? t("{value0} / {value1} containers running", {
                            value0: app.running_count,
                            value1: app.container_count ?? "?",
                          })
                        : translateText(app.description) ||
                          t("No description provided")}
                    </small>
                  </div>
                </div>
              ))
            )}
            {!!row.snapshot.storage?.length && (
              <>
                <h3>{t("External storage · read-only")}</h3>
                {row.snapshot.storage.map((storage, i) => (
                  <div key={String(storage.id ?? i)}>
                    <strong>{storage.name || storage.id}</strong>
                    <p>
                      {bytes(Number(storage.used_bytes || 0))}
                      {t(" used ·")} {bytes(Number(storage.free_bytes || 0))}
                      {t(" free ·")} {bytes(Number(storage.total_bytes || 0))}
                      {t(" total")}
                    </p>
                    {Number(storage.total_bytes) > 0 && (
                      <progress
                        aria-label={t("{value0} usage", {
                          value0: storage.name || "Storage",
                        })}
                        max={Number(storage.total_bytes)}
                        value={Number(storage.used_bytes || 0)}
                      />
                    )}
                  </div>
                ))}
              </>
            )}
            {!!Object.keys(row.snapshot.metrics || {}).length && (
              <>
                <h3>{t("Metrics")}</h3>
                <dl>
                  {Object.entries(row.snapshot.metrics || {}).map(
                    ([key, value]) => (
                      <div key={key}>
                        <dt>
                          {key.replaceAll("_", " ").replace(/([A-Z])/g, " $1")}
                        </dt>
                        <dd>
                          {key.endsWith("Bytes")
                            ? bytes(value)
                            : key.endsWith("Percent")
                              ? t("{value0}%", {
                                  value0: value.toLocaleString(getLocale(), {
                                    minimumFractionDigits: 1,
                                    maximumFractionDigits: 1,
                                    useGrouping: false,
                                  }),
                                })
                              : value}
                        </dd>
                      </div>
                    ),
                  )}
                </dl>
              </>
            )}
            {!!row.snapshot.events?.length && (
              <>
                <h3>{t("FjordHub events")}</h3>
                {row.snapshot.events.map((event, i) => (
                  <p key={String(event.id ?? i)}>
                    {t("FjordHub · ")}
                    {translateText(event.message) || event.type}
                  </p>
                ))}
              </>
            )}
          </div>
        </Panel>
      ))}
    </LayoutGroup>
  );
}
