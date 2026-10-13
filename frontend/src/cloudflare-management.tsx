import { useCallback, useEffect, useState } from "react";
import { Cloud, Download, Link2, Plus, RefreshCw } from "lucide-react";
import "./cloudflare.css";
import { api } from "./api";
import { Panel } from "./phase2";
import { NotificationPopup } from "./notification-popup";
import { t, translateText, useLanguage } from "./i18n";

type Route = {
  id: string;
  hostname: string;
  packageId: string;
  tunnelId: string;
  autoSync: boolean;
  lastApplied: string | null;
  status: string;
  message: string;
};
type Tunnel = { id: string; name: string; remote?: boolean };
type RecordRow = {
  id: string;
  zoneId: string;
  name: string;
  type: string;
  content: string;
  proxied: boolean;
};
type Management = {
  configured: boolean;
  accountId: string;
  tunnels: Tunnel[];
  routes: Route[];
  apps: { packageId: string; name: string }[];
  discovery?: {
    zones: { id: string; name: string }[];
    records: RecordRow[];
    tunnels: Tunnel[];
    issues: {
      resource: string;
      permission: string;
      message: string;
      code: string;
    }[];
    complete: boolean;
    checkedAt: number;
    apps: {
      packageId: string;
      name: string;
      origin: string | null;
      message: string;
    }[];
  };
};
const endpoint = "/cloudflare/manage";
const labels: Record<string, string> = {
  mediahub: "mediahub",
  "org.mediahub.mediaseed": "seed",
  "org.mediahub.mediavpn": "vpn",
  "org.mediahub.plex": "plex",
  "org.mediahub.jellyfin": "jellyfin",
};

export function CloudflareManagementPanel({
  onConfigured,
}: {
  onConfigured?: (value: boolean) => void;
}) {
  useLanguage();
  const [data, setData] = useState<Management>();
  const [account, setAccount] = useState("");
  const [token, setToken] = useState("");
  const [tunnel, setTunnel] = useState("");
  const [existingTunnel, setExistingTunnel] = useState("");
  const [zone, setZone] = useState("");
  const [record, setRecord] = useState("");
  const [app, setApp] = useState("mediahub");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    try {
      const value = await api<Management>(endpoint);
      setData(value);
      setAccount((current) => current || value.accountId);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => clearInterval(timer);
  }, [load]);
  useEffect(() => {
    if (data) onConfigured?.(data.configured);
  }, [data, onConfigured]);
  const change = async (
    path: string,
    method: "POST" | "PUT" | "DELETE",
    body: unknown,
    success: string,
  ) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setData(await api<Management>(endpoint + path, method, body));
      setMessage(success);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  };
  const download = async (id: string) => {
    setBusy(true);
    setError("");
    try {
      const auth = await api<{ csrf: string }>("/auth/me");
      const response = await fetch(
        "/api/v1" + endpoint + "/tunnels/" + id + "/token",
        {
          method: "POST",
          headers: { "X-MediaHub-CSRF": auth.csrf },
          credentials: "same-origin",
        },
      );
      if (!response.ok)
        throw new Error(t("Could not download connector token"));
      const url = URL.createObjectURL(await response.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = "cloudflared-token.txt";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const discovery = data?.discovery;
  const selectedZone =
    discovery?.zones.find((row) => row.id === zone) || discovery?.zones[0];
  const selectedTunnel =
    data?.tunnels.find((row) => row.id === tunnel) || data?.tunnels[0];
  const records =
    discovery?.records.filter((row) => row.zoneId === selectedZone?.id) || [];
  const availableTunnels =
    discovery?.tunnels.filter(
      (row) =>
        row.remote && !data?.tunnels.some((saved) => saved.id === row.id),
    ) || [];
  const selectedApp = discovery?.apps.find((row) => row.packageId === app);
  const generatedHostname = selectedZone
    ? labels[app] + "." + selectedZone.name
    : "";
  const compatible = (row: RecordRow) =>
    row.type === "CNAME" &&
    row.proxied &&
    row.content.replace(/\.$/, "") === selectedTunnel?.id + ".cfargotunnel.com";
  const selectedRecord = records.find((row) => row.id === record);
  const generatedConflict = records.some(
    (row) => row.name === generatedHostname && !compatible(row),
  );
  return (
    <Panel title={t("Manage Cloudflare tunnels")}>
      <p className="muted">
        {t(
          "Choose your domains, DNS records and apps. MediaHub discovers addresses and follows local IP and port changes automatically.",
        )}
      </p>
      {error && (
        <NotificationPopup tone="danger">
          {translateText(error)}
        </NotificationPopup>
      )}
      {message && (
        <NotificationPopup tone="success">
          {translateText(message)}
        </NotificationPopup>
      )}
      {!data ? (
        <p>{t("Loading Cloudflare account...")}</p>
      ) : !data.configured ? (
        <form
          className="cloudflare-management-form"
          onSubmit={(e) => {
            e.preventDefault();
            void change(
              "/credentials",
              "PUT",
              { accountId: account, token },
              "Cloudflare account connected",
            ).then((ok) => {
              if (ok) setToken("");
            });
          }}
        >
          <label>
            {t("Cloudflare account ID")}
            <input
              required
              value={account}
              maxLength={32}
              pattern="[a-fA-F0-9]{32}"
              onChange={(e) => setAccount(e.target.value)}
              autoComplete="off"
            />
          </label>
          <label>
            {t("Cloudflare API token")}
            <input
              required
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoComplete="new-password"
            />
          </label>
          <button disabled={busy} type="submit">
            <Cloud size={16} />
            {t("Connect account")}
          </button>
        </form>
      ) : null}
      <details
        className="cloudflare-requirements"
        open={!data?.configured || !!discovery?.issues.length}
      >
        <summary>{t("Access and automatic setup")}</summary>
        <ul>
          <li>
            {t(
              "Read domains: Zone > Zone > Read, limited to the domains you want to use.",
            )}
          </li>
          <li>
            {t(
              "Read DNS records: Zone > DNS > Read or Edit. Publishing and synchronizing requires Edit.",
            )}
          </li>
          <li>
            {t(
              "Read tunnels: Account > Cloudflare Tunnel > Read or Edit. Creating tunnels, publishing routes and installing connectors requires Edit.",
            )}
          </li>
          <li>
            {t(
              "Apps on other servers need a connected MediaHub Agent. Install the connector on MediaHub to use its prepared HTTPS certificate automatically.",
            )}
          </li>
          <li>
            {t(
              "VPN integration needs no Proton password or VPN private key in Cloudflare. MediaHub follows the local app web address, not the VPN public IP or torrent forwarding port.",
            )}
          </li>
        </ul>
        <p className="muted">
          {t(
            "Read access is checked when discovering resources. Write access is checked when you perform an action. A successful read does not verify Edit permission.",
          )}
        </p>
        <a
          href="https://dash.cloudflare.com/profile/api-tokens"
          target="_blank"
          rel="noreferrer"
        >
          {t("Manage Cloudflare API permissions")}
        </a>
      </details>
      {data?.configured && (
        <>
          <div className="runtime-toolbar">
            <strong>{t("API connected")}</strong>
            {discovery?.checkedAt && (
              <small className="muted">
                {t("Last checked")}:{" "}
                {new Date(discovery.checkedAt * 1000).toLocaleTimeString()}
              </small>
            )}
            <button
              disabled={busy}
              onClick={() =>
                void change(
                  "/discover",
                  "POST",
                  {},
                  "Cloudflare resources refreshed",
                )
              }
            >
              <RefreshCw size={16} />
              {t("Refresh domains and records")}
            </button>
          </div>
          {discovery?.issues.map((issue) => (
            <div className="cloudflare-access-issue" key={issue.resource}>
              <strong>{issue.resource}</strong>
              <p>{translateText(issue.message)}</p>
              <small>
                {t("Required access")}: {issue.permission}
              </small>
            </div>
          ))}
          {discovery && !discovery.complete && (
            <p className="muted">
              {t(
                "Discovery is incomplete. Previously fetched records may be shown; publishing is disabled until access is restored.",
              )}
            </p>
          )}
          {discovery?.complete && !discovery.zones.length && (
            <p>
              {t(
                "No domains are accessible in this account. Check the account and the token's selected zones.",
              )}
            </p>
          )}
          <div className="cloudflare-management-form">
            <label>
              {t("Domain")}
              <select
                value={selectedZone?.id || ""}
                disabled={busy || !discovery?.zones.length}
                onChange={(e) => {
                  setZone(e.target.value);
                  setRecord("");
                }}
              >
                {!discovery?.zones.length && (
                  <option value="">{t("No accessible domains")}</option>
                )}
                {discovery?.zones.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <details open>
            <summary>
              {t("Existing DNS records")} ({records.length})
            </summary>
            <div className="cloudflare-profile-list">
              {records.map((row) => (
                <article key={row.id}>
                  <div>
                    <strong>{row.name}</strong>
                    <small>
                      {row.type}
                      {row.content ? " - " + row.content : ""}
                    </small>
                  </div>
                </article>
              ))}
            </div>
            {!records.length && (
              <p className="muted">{t("No records found for this domain.")}</p>
            )}
          </details>
          <div className="cloudflare-management-form">
            {!!availableTunnels.length && (
              <>
                <label>
                  {t("Existing tunnel")}
                  <select
                    value={existingTunnel || availableTunnels[0].id}
                    onChange={(e) => setExistingTunnel(e.target.value)}
                  >
                    {availableTunnels.map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.name}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  disabled={busy || !discovery?.complete}
                  onClick={() =>
                    void change(
                      "/tunnels/" +
                        (existingTunnel || availableTunnels[0].id) +
                        "/adopt",
                      "POST",
                      {},
                      "Existing tunnel selected. Unrelated routes were preserved.",
                    )
                  }
                >
                  {t("Use selected tunnel")}
                </button>
              </>
            )}
            <button
              disabled={busy}
              onClick={() =>
                void change(
                  "/tunnels",
                  "POST",
                  { name: "MediaHub" },
                  "Tunnel created. Connect a cloudflared connector to bring it online.",
                )
              }
            >
              <Plus size={16} />
              {t("Create tunnel")}
            </button>
          </div>
          <div className="cloudflare-profile-list">
            {data.tunnels.map((item) => (
              <article key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  <small>{item.id}</small>
                </div>
                <button disabled={busy} onClick={() => void download(item.id)}>
                  <Download size={16} />
                  {t("Download connector token")}
                </button>
                <button
                  disabled={busy}
                  onClick={() =>
                    void change(
                      "/tunnels/" + item.id + "/install-connector",
                      "POST",
                      {},
                      "Connector started on the MediaHub host",
                    )
                  }
                >
                  <Download size={16} />
                  {t("Install connector on MediaHub")}
                </button>
              </article>
            ))}
          </div>
          {!!data.tunnels.length && (
            <form
              className="cloudflare-management-form"
              onSubmit={(e) => {
                e.preventDefault();
                void change(
                  "/routes/discovered",
                  "POST",
                  {
                    tunnelId: selectedTunnel?.id,
                    zoneId: selectedZone?.id,
                    packageId: app,
                    recordId: record || null,
                  },
                  "App route saved. Check its synchronization status below.",
                );
              }}
            >
              <label>
                {t("Tunnel")}
                <select
                  value={selectedTunnel?.id || ""}
                  onChange={(e) => {
                    setTunnel(e.target.value);
                    setRecord("");
                  }}
                >
                  {data.tunnels.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("App")}
                <select
                  value={app}
                  onChange={(e) => {
                    setApp(e.target.value);
                    setRecord("");
                  }}
                >
                  {data.apps.map((row) => (
                    <option key={row.packageId} value={row.packageId}>
                      {row.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("Public hostname")}
                <select
                  value={record}
                  onChange={(e) => setRecord(e.target.value)}
                >
                  <option value="" disabled={generatedConflict}>
                    {generatedHostname} ({t("Automatic")})
                  </option>
                  {records
                    .filter(
                      (row) =>
                        row.type === "CNAME" ||
                        row.type === "A" ||
                        row.type === "AAAA",
                    )
                    .map((row) => (
                      <option
                        key={row.id}
                        value={row.id}
                        disabled={!compatible(row)}
                      >
                        {row.name} - {row.type}
                        {!compatible(row)
                          ? " (" + t("Points elsewhere") + ")"
                          : ""}
                      </option>
                    ))}
                </select>
              </label>
              <button
                type="submit"
                disabled={
                  busy ||
                  !discovery?.complete ||
                  !selectedApp?.origin ||
                  !selectedZone ||
                  (!record && generatedConflict) ||
                  (!!record && (!selectedRecord || !compatible(selectedRecord)))
                }
              >
                <Link2 size={16} />
                {t("Link app and publish hostname")}
              </button>
              <p className="muted">
                {selectedApp?.origin ||
                  translateText(
                    selectedApp?.message ||
                      "Install or connect this app in MediaHub first.",
                  )}
              </p>
              {generatedConflict && (
                <p className="muted">
                  {t(
                    "The automatic hostname already points elsewhere. Choose a matching tunnel record; existing records are preserved.",
                  )}
                </p>
              )}
            </form>
          )}
          <div className="cloudflare-profile-list">
            {data.routes.map((route) => (
              <article key={route.id}>
                <div>
                  <strong>{route.hostname}</strong>
                  <small>
                    {
                      data.apps.find(
                        (item) => item.packageId === route.packageId,
                      )?.name
                    }{" "}
                    {"\u2192"} {route.lastApplied || t("Pending")}
                  </small>
                  <span>{translateText(route.message)}</span>
                </div>
                <label>
                  <input
                    type="checkbox"
                    checked={route.autoSync}
                    disabled={busy}
                    onChange={(e) =>
                      void change(
                        "/routes/" + route.id,
                        "PUT",
                        { autoSync: e.target.checked },
                        "Automatic synchronization updated",
                      )
                    }
                  />
                  {t("Follow app IP and port")}
                </label>
              </article>
            ))}
          </div>
          <div className="runtime-toolbar">
            <button
              disabled={busy}
              onClick={() =>
                void change(
                  "/sync",
                  "POST",
                  {},
                  "Route synchronization checked",
                )
              }
            >
              <RefreshCw size={16} />
              {t("Synchronize now")}
            </button>
            <button
              disabled={busy}
              onClick={() =>
                void change(
                  "/credentials",
                  "DELETE",
                  undefined,
                  "Cloudflare disconnected. Remote tunnels and DNS records were kept.",
                )
              }
            >
              {t("Disconnect account")}
            </button>
          </div>
        </>
      )}
    </Panel>
  );
}
