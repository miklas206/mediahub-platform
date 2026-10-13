import { useCallback, useEffect, useState } from "react";
import { Cloud, Plus, RefreshCw } from "lucide-react";
import "./cloudflare.css";
import { api } from "./api";
import { Panel } from "./phase2";
import { NotificationPopup } from "./notification-popup";
import { t, translateText, useLanguage } from "./i18n";
type Management = {
  configured: boolean;
  accountId: string;
  vpn: {
    message: string | null;
    profiles: {
      id: string;
      name: string;
      publicIp: string | null;
      type: string | null;
      ready: boolean;
      forwardedPort: number | null;
    }[];
  };
  vpnRecords: {
    id: string;
    hostname: string;
    profileId: string;
    content: string | null;
    type: string | null;
    autoSync: boolean;
    status: string;
    message: string;
    forwardedPort?: number | null;
  }[];
  discovery?: {
    zones: { id: string; name: string }[];
    records: {
      id: string;
      zoneId: string;
      name: string;
      type: string;
      content: string;
    }[];
    tunnels: { id: string; name: string; remote: boolean }[];
    issues: { resource: string; permission: string; message: string }[];
    complete: boolean;
    checkedAt: number;
  };
};
const endpoint = "/cloudflare/manage";
export function CloudflareManagementPanel({
  onConfigured,
}: {
  onConfigured?: (value: boolean) => void;
}) {
  useLanguage();
  const [data, setData] = useState<Management>();
  const [account, setAccount] = useState("");
  const [token, setToken] = useState("");
  const [zone, setZone] = useState("");
  const [profile, setProfile] = useState("");
  const [label, setLabel] = useState("vpn");
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
      if (path === "/credentials") setToken("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const discovery = data?.discovery;
  const selectedZone =
    discovery?.zones.find((row) => row.id === zone) || discovery?.zones[0];
  const profiles = data?.vpn?.profiles || [];
  const selectedProfile =
    profiles.find((row) => row.id === profile) || profiles[0];
  const dnsIssues =
    discovery?.issues.filter((row) => row.resource !== "tunnels") || [];
  const records =
    discovery?.records.filter((row) => row.zoneId === selectedZone?.id) || [];
  const tunnels = discovery?.tunnels || [];
  return (
    <Panel title={t("Cloudflare DNS and VPN")}>
      <p className="muted">
        {t(
          "Create DNS records using a verified MediaVPN public IP. Existing Cloudflare tunnels are shown read-only.",
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
            );
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
              "DNS records require Zone > DNS > Edit. Viewing existing tunnels only requires Account > Cloudflare Tunnel > Read.",
            )}
          </li>
          <li>
            {t(
              "MediaVPN must have a running, verified profile. Its public IP is fetched automatically; no manual IP or VPN private key is needed.",
            )}
          </li>
        </ul>
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
          <h3>{t("Create VPN DNS record")}</h3>
          <p className="muted">
            {t(
              "DNS points to the VPN public IP; it does not open an app port. A and AAAA records cannot store a forwarding port. The service must already be reachable through the VPN.",
            )}
          </p>
          {data.vpn?.message && (
            <p className="muted">{translateText(data.vpn.message)}</p>
          )}
          <form
            className="cloudflare-management-form"
            onSubmit={(e) => {
              e.preventDefault();
              void change(
                "/vpn-dns",
                "POST",
                {
                  zoneId: selectedZone?.id,
                  label,
                  profileId: selectedProfile?.id,
                },
                "VPN DNS request saved. Check its synchronization status below.",
              );
            }}
          >
            <label>
              {t("Domain")}
              <select
                required
                disabled={!discovery?.zones.length || busy}
                value={selectedZone?.id || ""}
                onChange={(e) => setZone(e.target.value)}
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
            <label>
              {t("Record name")}
              <input
                required
                aria-label={t("Record name")}
                value={label}
                pattern="[A-Za-z0-9][A-Za-z0-9.-]*"
                maxLength={100}
                onChange={(e) => setLabel(e.target.value)}
              />
              <small>
                {label}.{selectedZone?.name || "..."}
              </small>
            </label>
            <label>
              {t("VPN profile")}
              <select
                required
                disabled={busy || !profiles.length}
                value={selectedProfile?.id || ""}
                onChange={(e) => setProfile(e.target.value)}
              >
                {!profiles.length && (
                  <option value="">{t("No VPN profiles available")}</option>
                )}
                {profiles.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                    {row.ready
                      ? " - " + row.publicIp
                      : " (" + t("Not verified") + ")"}
                  </option>
                ))}
              </select>
            </label>
            <div>
              <small>{t("Automatic DNS target")}</small>
              <p>
                {selectedProfile?.publicIp
                  ? selectedProfile.type + " - " + selectedProfile.publicIp
                  : t(
                      "Start and verify the selected MediaVPN profile before publishing DNS",
                    )}
              </p>
            </div>
            <button
              disabled={
                busy ||
                !selectedZone ||
                !selectedProfile?.ready ||
                !!dnsIssues.length
              }
              type="submit"
            >
              <Plus size={16} />
              {t("Create DNS record")}
            </button>
          </form>
          <h3>{t("VPN DNS records")}</h3>
          <div className="cloudflare-profile-list">
            {(data.vpnRecords || []).map((row) => (
              <article key={row.id}>
                <div>
                  <strong>{row.hostname}</strong>
                  <small>
                    {row.type || "DNS"} - {row.content || t("Pending")}
                  </small>
                  <p>{translateText(row.message)}</p>
                  {row.forwardedPort && (
                    <small>
                      {t("VPN forwarding port")}: {row.forwardedPort} (
                      {t("not stored in DNS")})
                    </small>
                  )}
                </div>
                <label>
                  <input
                    type="checkbox"
                    checked={row.autoSync}
                    disabled={busy}
                    onChange={(e) =>
                      void change(
                        "/vpn-dns/" + row.id,
                        "PUT",
                        { autoSync: e.target.checked },
                        "Automatic synchronization updated",
                      )
                    }
                  />
                  {t("Follow VPN IP")}
                </label>
              </article>
            ))}
          </div>
          <button
            disabled={busy}
            onClick={() =>
              void change(
                "/sync",
                "POST",
                {},
                "VPN DNS synchronization checked",
              )
            }
          >
            <RefreshCw size={16} />
            {t("Synchronize now")}
          </button>
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
          <details open>
            <summary>
              {t("Existing tunnels (read-only)")} ({tunnels.length})
            </summary>
            <div className="cloudflare-profile-list">
              {tunnels.map((row) => (
                <article key={row.id}>
                  <div>
                    <strong>{row.name}</strong>
                    <small>{row.id}</small>
                  </div>
                </article>
              ))}
            </div>
            {!tunnels.length && (
              <p className="muted">
                {t("No tunnels found or tunnel read access is missing.")}
              </p>
            )}
          </details>
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
        </>
      )}
    </Panel>
  );
}
