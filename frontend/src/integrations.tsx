import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { bytes } from "./format";
import { ErrorBox, Panel } from "./phase2";
import "./integrations.css";

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
type Integration = {
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
const label = (s: string) => statusLabels[s] || s;

function useIntegrations() {
  const [items, setItems] = useState<Integration[]>([]),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    try {
      setItems(await api<Integration[]>("/integrations"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload();
    const timer = setInterval(() => void reload(), 15000);
    return () => clearInterval(timer);
  }, [reload]);
  return { items, error, loading, reload };
}

export function IntegrationsCard() {
  const { items, error, loading } = useIntegrations();
  return (
    <Panel title="External integrations">
      <ErrorBox error={error} />
      {loading ? (
        <p role="status">Loading integrations…</p>
      ) : !items.length ? (
        <p>
          No external integrations configured. MediaHub works independently.
        </p>
      ) : (
        items.map((row) => (
          <div className="app-row" key={row.id}>
            <div className="app-row-name">
              <strong>{row.name}</strong>
              <small>
                {label(row.snapshot.status)} ·{" "}
                {(row.snapshot.apps || []).length} {row.snapshot.capabilities?.includes("docker.resources.read") ? "app groups" : "catalog entries"}
              </small>
            </div>
            <Link to="/integrations">View</Link>
          </div>
        ))
      )}
      <Link className="text-link" to="/integrations">
        Manage FjordHub integration →
      </Link>
    </Panel>
  );
}

export function IntegrationsPage() {
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
    void api<{baseUrl: string | null}>("/integrations/fjordhub/defaults")
      .then((value) => { if (value.baseUrl) setUrl((current) => current || value.baseUrl!); })
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
      }
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
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="stack integrations-page">
      <div>
        <p className="muted">
          Read-only external services. Separate from managed hosts and apps.
        </p>
      </div>
      <ErrorBox error={error || failure} />
      {notice && <p role="status">{notice}</p>}
      <Panel title="Connect FjordHub">
        <form onSubmit={submit} className="stack">
          <label>
            Display name
            <input
              required
              maxLength={80}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            FjordHub URL
            <input
              required
              type="url"
              value={baseUrl}
              placeholder="http://your-fjordhub-lan-ip:port"
              onChange={(e) => {
                setUrl(e.target.value);
                setTest(null);
              }}
            />
          </label>
          <p className="muted">
            Enter FjordHub’s normal local URL, without an API path. MediaHub adds
            the supported read-only route automatically. Current FjordHub versions
            expose Docker resource usage; older versions may expose only a catalog. Public
            Cloudflare access cannot be used for this LAN-only endpoint.
          </p>
          <label>
            Access Token
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
            Allow HTTP to this LAN-only FjordHub API
          </label>
          {allowHttp && (
            <p role="note">
              The Access Token is not encrypted between Core and an HTTP API.
              Prefer verified HTTPS. Browser submission to MediaHub still
              requires HTTPS.
            </p>
          )}
          <div className="button-row">
            <button
              type="button"
              disabled={busy || token.length < 16 || !baseUrl}
              onClick={() => void act("test")}
            >
              Test Connection
            </button>
            <button type="submit" disabled={busy || token.length < 16}>
              {busy ? "Working…" : "Save"}
            </button>
          </div>
          {test && (
            <div role="status">
              <strong>{label(test.status)}</strong>
              <p>
                FjordHub {test.version || "version unavailable"} · API{" "}
                {test.api_version || "not verified"}
              </p>
              {test.status === "online" && <p>{test.apps?.length ?? 0} entries found · Capabilities: {test.capabilities?.join(", ")} · Read-only integration</p>}
              {test.failed_endpoint && (
                <p>Endpoint requiring attention: {test.failed_endpoint}</p>
              )}
            </div>
          )}
        </form>
      </Panel>
      {loading && <p role="status">Loading configured integrations…</p>}
      {!loading && !items.length && (
        <Panel title="No integrations yet">
          <p>
            Add FjordHub above. It is optional and cannot affect Core health.
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
                Showing the last successful snapshot; these values are not live.
              </p>
            )}
            {row.snapshot.failed_endpoint && (
              <p>
                Endpoint requiring attention: {row.snapshot.failed_endpoint}
              </p>
            )}
            <dl>
              <dt>Access Token</dt>
              <dd>{row.tokenConfigured ? "Configured" : "Not configured"}</dd>
              <dt>Last successful sync</dt>
              <dd>
                {row.lastSuccessfulSync
                  ? new Date(row.lastSuccessfulSync).toLocaleString()
                  : "Not yet verified"}
              </dd>
              <dt>Version</dt>
              <dd>{row.snapshot.version || "Unavailable"}</dd>
              <dt>API version</dt>
              <dd>{row.snapshot.api_version || "Unverified"}</dd>
            </dl>
            <div className="button-row">
              <button
                disabled={busy || !row.enabled}
                onClick={() => void manage(row.id, "refresh")}
              >
                Refresh
              </button>
              <button
                disabled={busy || !row.enabled}
                onClick={() => void manage(row.id, "disconnect")}
              >
                Disconnect
              </button>
            </div>
            <small className="muted">
              Refresh respects provider backoff and the sync interval. External
              storage is informational, never mounted by MediaHub.
            </small>
            {(row.snapshot.warnings || []).map((warning, i) => (
              <p role="note" key={i}>
                {warning}
              </p>
            ))}
            <h3>{row.snapshot.capabilities?.includes("docker.resources.read") ? "Installed app groups" : "Installable app catalog"}</h3>
            {!row.snapshot.apps?.length ? (
              <p>No apps reported by the API.</p>
            ) : (
              row.snapshot.apps.map((app, i) => (
                <div className="app-row" key={String(app.id ?? i)}>
                  <div className="app-row-name">
                    <strong>{app.name || app.id || "Unnamed app"}</strong>
                    <small>
                      {app.running_count !== undefined ? `${app.running_count} / ${app.container_count ?? "?"} containers running` : app.description || "No description provided"}
                    </small>
                  </div>
                </div>
              ))
            )}
            {!!row.snapshot.storage?.length && (
              <>
                <h3>External storage · read-only</h3>
                {row.snapshot.storage.map((storage, i) => (
                  <div key={String(storage.id ?? i)}>
                    <strong>{storage.name || storage.id}</strong>
                    <p>
                      {bytes(Number(storage.used_bytes || 0))} used ·{" "}
                      {bytes(Number(storage.free_bytes || 0))} free ·{" "}
                      {bytes(Number(storage.total_bytes || 0))} total
                    </p>
                    {Number(storage.total_bytes) > 0 && (
                      <progress
                        aria-label={`${storage.name || "Storage"} usage`}
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
                <h3>Metrics</h3>
                <dl>
                  {Object.entries(row.snapshot.metrics || {}).map(
                    ([key, value]) => (
                      <div key={key}>
                        <dt>{key.replaceAll("_", " ").replace(/([A-Z])/g, " $1")}</dt>
                        <dd>{key.endsWith("Bytes") ? bytes(value) : key.endsWith("Percent") ? `${value.toFixed(1)}%` : value}</dd>
                      </div>
                    ),
                  )}
                </dl>
              </>
            )}
            {!!row.snapshot.events?.length && (
              <>
                <h3>FjordHub events</h3>
                {row.snapshot.events.map((event, i) => (
                  <p key={String(event.id ?? i)}>
                    FjordHub · {event.message || event.type}
                  </p>
                ))}
              </>
            )}
          </div>
        </Panel>
      ))}
    </div>
  );
}
