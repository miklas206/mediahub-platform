import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { useData } from "./use-data";
import { t } from "./i18n";
import { NotificationPopup } from "./notification-popup";

type Gateway = {
  configured: boolean;
  enabled: boolean;
  zones: { id: string; name: string }[];
  routes: {
    packageId: string;
    zoneId: string;
    label: string;
    hostname: string;
    httpsVerified: boolean;
    message?: string;
  }[];
};
export function AppVPNDomainPanel({ appId, app = "plex" }: { appId: string; app?: "plex" | "jellyfin" }) {
  const { data, error, reload } = useData<Gateway>("/vpn-gateway");
  const [draft, setDraft] = useState<{ zoneId: string; label: string } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const timer = setInterval(() => {
      if (!document.hidden) reload();
    }, 10000);
    return () => clearInterval(timer);
  }, [reload]);
  const route = data?.routes.find(
    (row) => row.packageId === "org.mediahub." + app,
  );
  const value = draft ?? {
    zoneId: route?.zoneId || data?.zones[0]?.id || "",
    label: route?.label || app,
  };
  const ready = data?.configured && data.enabled && data.zones.length > 0;
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure("");
    setNotice("");
    try {
      await api(
        `/vpn-gateway/apps/${encodeURIComponent(appId)}/domain`,
        "PUT",
        value,
      );
      setDraft(null);
      reload();
      setNotice(
        t(app === "plex" ? "Plex domain saved. MediaVPN manages DNS and HTTPS automatically." : "Jellyfin domain saved. MediaVPN manages DNS and HTTPS automatically."),
      );
      window.dispatchEvent(new Event("apps-changed"));
    } catch (error) {
      setFailure((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel app-vpn-domain">
      <div className="panel-heading">
        <h2>{t(app === "plex" ? "Plex domain through MediaVPN" : "Jellyfin domain through MediaVPN")}</h2>
      </div>
      <div className="phase-content">
        {(error || failure) && (
          <NotificationPopup tone="danger">
            {failure || error}
          </NotificationPopup>
        )}
        {notice && (
          <NotificationPopup tone="success">{notice}</NotificationPopup>
        )}
        <p>
          {t(
            "MediaVPN manages this domain, its certificate and the current VPN address automatically.",
          )}
        </p>
        {data && !ready && (
          <p>
            {t(
              "Enable the shared gateway and connect Cloudflare in MediaVPN first.",
            )}
          </p>
        )}
        {data && (
          <form
            className="settings-form"
            onSubmit={(event) => void save(event)}
          >
            <label>
              {t("Domain")}
              <select
                value={value.zoneId}
                disabled={busy || !ready}
                onChange={(event) =>
                  setDraft({ ...value, zoneId: event.target.value })
                }
              >
                {!value.zoneId && <option value="">{t("Choose")}</option>}
                {data.zones.map((zone) => (
                  <option key={zone.id} value={zone.id}>
                    {zone.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("Subdomain")}
              <input
                value={value.label}
                maxLength={100}
                required
                disabled={busy || !ready}
                onChange={(event) =>
                  setDraft({ ...value, label: event.target.value })
                }
              />
            </label>
            <p className="muted">
              {value.label}.
              {data.zones.find((zone) => zone.id === value.zoneId)?.name ||
                "..."}
            </p>
            {route && (
              <p role="status">
                {route.hostname}:{" "}
                {t(
                  route.httpsVerified
                    ? "HTTPS verified"
                    : route.message || "Checking...",
                )}
              </p>
            )}
            <div className="button-row">
              <button
                type="submit"
                disabled={
                  busy || !ready || !value.zoneId || !value.label.trim()
                }
              >
                {t(app === "plex" ? "Save Plex domain" : "Save Jellyfin domain")}
              </button>
              <Link className="button-link" to="/store/mediavpn">
                {t("Open MediaVPN")}
              </Link>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
