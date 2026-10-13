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
type Management = {
  configured: boolean;
  accountId: string;
  tunnels: { id: string; name: string }[];
  routes: Route[];
  apps: { packageId: string; name: string }[];
};
const endpoint = "/cloudflare/manage";

export function CloudflareManagementPanel() {
  useLanguage();
  const [data, setData] = useState<Management>();
  const [account, setAccount] = useState("");
  const [token, setToken] = useState("");
  const [name, setName] = useState("");
  const [tunnel, setTunnel] = useState("");
  const [zone, setZone] = useState("");
  const [hostname, setHostname] = useState("");
  const [app, setApp] = useState("mediahub");
  const [caPool, setCaPool] = useState("/etc/cloudflared/mediahub-ca.pem");
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
  const change = async (
    path: string,
    method: string,
    body: unknown,
    success: string,
  ) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setData(
        await api<Management>(
          endpoint + path,
          method as "POST" | "PUT" | "DELETE",
          body,
        ),
      );
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
  return (
    <Panel title={t("Manage Cloudflare tunnels")}>
      <p className="muted">
        {t(
          "Create tunnels and link public hostnames to your apps. Linked routes follow local IP and port changes automatically.",
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
        <button disabled={busy || !data} type="submit">
          <Cloud size={16} />
          {t(data?.configured ? "Replace API token" : "Connect account")}
        </button>
      </form>
      <p className="muted">
        {t(
          "Token permissions: Account Cloudflare Tunnel Edit, Zone Read and DNS Edit for your selected zones. The token is stored encrypted.",
        )}
      </p>
      {data?.configured && (
        <>
          <form
            className="runtime-toolbar"
            onSubmit={(e) => {
              e.preventDefault();
              void change(
                "/tunnels",
                "POST",
                { name },
                "Tunnel created. Connect a cloudflared connector to bring it online.",
              ).then((ok) => {
                if (ok) setName("");
              });
            }}
          >
            <label>
              {t("New tunnel name")}
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={100}
              />
            </label>
            <button type="submit" disabled={busy}>
              <Plus size={16} />
              {t("Create tunnel")}
            </button>
          </form>
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
              </article>
            ))}
          </div>
          {!!data.tunnels.length && (
            <>
              <details>
                <summary>{t("Connect the tunnel")}</summary>
                <p>
                  {t(
                    "Download the connector token and place it on the connector host. Run cloudflared with this token file. For local HTTPS apps, mount the MediaHub CA at the CA path below. Creating a tunnel does not install or start a connector.",
                  )}
                </p>
                <code>
                  cloudflared tunnel --no-autoupdate run --token-file
                  /path/to/cloudflared-token.txt
                </code>
              </details>
              <form
                className="cloudflare-management-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void change(
                    "/routes",
                    "POST",
                    {
                      tunnelId: tunnel || data.tunnels[0].id,
                      zoneId: zone,
                      hostname,
                      packageId: app,
                      autoSync: true,
                      caPool,
                    },
                    "App route saved. Check its synchronization status below.",
                  );
                }}
              >
                <label>
                  {t("Tunnel")}
                  <select
                    value={tunnel || data.tunnels[0].id}
                    onChange={(e) => setTunnel(e.target.value)}
                  >
                    {data.tunnels.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  {t("App")}
                  <select value={app} onChange={(e) => setApp(e.target.value)}>
                    {data.apps.map((item) => (
                      <option key={item.packageId} value={item.packageId}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  {t("Cloudflare zone ID")}
                  <input
                    required
                    pattern="[a-fA-F0-9]{32}"
                    value={zone}
                    onChange={(e) => setZone(e.target.value)}
                  />
                </label>
                <label>
                  {t("Public hostname")}
                  <input
                    required
                    placeholder="seed.example.com"
                    value={hostname}
                    onChange={(e) => setHostname(e.target.value)}
                  />
                </label>
                <label>
                  {t("Connector CA path")}
                  <input
                    required
                    value={caPool}
                    onChange={(e) => setCaPool(e.target.value)}
                  />
                </label>
                <button type="submit" disabled={busy}>
                  <Link2 size={16} />
                  {t("Link app and publish hostname")}
                </button>
              </form>
            </>
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
