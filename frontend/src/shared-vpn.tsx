import { useEffect, useState } from "react";
import { Shield, RefreshCw } from "lucide-react";
import { api } from "./api";
import { Panel } from "./phase2";
import { NotificationPopup } from "./notification-popup";
import { t, translateText } from "./i18n";
import { useData } from "./use-data";

type Shared = {
  gateway: {
    enabled: boolean;
    ready: boolean;
    profileId: string | null;
    publicIp: string | null;
    profiles: { id: string; name: string }[];
    message: string | null;
  };
  apps: {
    id: string;
    name: string;
    hostId: string;
    enabled: boolean | null;
    ready: boolean;
    phase: string;
    message?: string | null;
  }[];
};

export function SharedVPNPanel() {
  const { data, error, reload } = useData<Shared>("/shared-vpn");
  const [profile, setProfile] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState<{
    id: string;
    enabled: boolean;
  } | null>(null);
  useEffect(() => {
    if (
      pending &&
      data?.apps.some(
        (app) => app.id === pending.id && app.enabled === pending.enabled,
      )
    )
      setPending(null);
  }, [data, pending]);
  useEffect(() => {
    const timer = setInterval(reload, 10000);
    return () => clearInterval(timer);
  }, [reload]);
  async function change(path: string, body: object) {
    setBusy(true);
    setFailure("");
    setMessage("");
    try {
      await api("/shared-vpn/" + path, "PUT", body);
      setMessage(t("VPN selection saved"));
      reload();
    } catch (error) {
      setPending(null);
      setFailure((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Panel title={t("Shared VPN")}>
      <p className="muted">
        {t(
          "Use one VPN profile for your apps. Local web addresses stay the same. Apps selected here have no direct internet fallback.",
        )}
      </p>
      {(error || failure) && (
        <NotificationPopup tone="danger">
          {translateText(failure || error)}
        </NotificationPopup>
      )}
      {message && (
        <NotificationPopup tone="success">{message}</NotificationPopup>
      )}
      <div className="button-row">
        <label>
          {t("VPN profile")}
          <select
            value={profile || data?.gateway.profileId || ""}
            disabled={busy || !data}
            onChange={(e) => setProfile(e.target.value)}
          >
            <option value="">{t("Choose a profile")}</option>
            {data?.gateway.profiles.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <button
          className="primary"
          disabled={busy || !(profile || data?.gateway.profileId)}
          onClick={() =>
            void change("gateway", {
              enabled: true,
              profileId: profile || data?.gateway.profileId,
            })
          }
        >
          <Shield size={16} />
          {t("Enable shared VPN")}
        </button>
        <button
          disabled={busy || !data?.gateway.enabled}
          onClick={() =>
            void change("gateway", {
              enabled: false,
              profileId: data?.gateway.profileId,
            })
          }
        >
          {t("Stop shared VPN")}
        </button>
        <button disabled={busy} onClick={reload}>
          <RefreshCw size={16} />
          {t("Refresh")}
        </button>
      </div>
      {data && (
        <p role="status">
          {t(
            data.gateway.ready
              ? "Shared VPN verified"
              : "Shared VPN not verified",
          )}
          {data.gateway.publicIp ? " · " + data.gateway.publicIp : ""}
        </p>
      )}
      {data?.gateway.message && (
        <p role="status" className="muted">
          {translateText(data.gateway.message)}
        </p>
      )}
      {data?.apps.map((app) => (
        <div key={app.id} className="runtime-toolbar">
          <strong>{app.name}</strong>
          <span className="muted">
            {app.hostId} · {t(app.ready ? "Connected" : "Not connected")}
            {app.message && <small>{translateText(app.message)}</small>}
          </span>
          <label>
            <input
              type="checkbox"
              checked={
                pending?.id === app.id ? pending.enabled : app.enabled === true
              }
              disabled={
                busy ||
                app.enabled === null ||
                (!app.enabled && !data.gateway.ready)
              }
              onChange={(e) => {
                setPending({ id: app.id, enabled: e.target.checked });
                void change("apps/" + app.id, { enabled: e.target.checked });
              }}
            />
            {t("Use shared VPN")}
          </label>
        </div>
      ))}
      <p className="muted">
        {t(
          "MediaSeed requires port forwarding on the chosen profile. Other hosts must be paired with MediaHub and able to reach the gateway over your private network.",
        )}
      </p>
    </Panel>
  );
}
