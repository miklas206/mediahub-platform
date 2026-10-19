import { useEffect, useState } from "react";
import { Shield, RefreshCw } from "lucide-react";
import { api } from "./api";
import { Panel } from "./phase2";
import { NotificationPopup } from "./notification-popup";
import { t, translateText } from "./i18n";
import { useData } from "./use-data";
import { useConfirm } from "./confirmation-dialog";

type Shared = {
  orphans?: { id: string; name: string; hostId: string }[];
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

export function SharedVPNPanel({ appsOnly = false }: { appsOnly?: boolean }) {
  const confirm = useConfirm();
  const { data, error, reload, poll } = useData<Shared>("/shared-vpn");
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
    const timer = setInterval(poll, 10000);
    return () => clearInterval(timer);
  }, [poll]);
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
  async function cleanup(id: string) {
    if (
      !(await confirm(
        "Remove this obsolete VPN connection? The app is already uninstalled. Media and VPN profiles are preserved.",
        {
          title: "Remove obsolete VPN connection",
          confirmLabel: "Remove connection",
          danger: true,
        },
      ))
    )
      return;
    setBusy(true);
    setFailure("");
    setMessage("");
    try {
      await api("/shared-vpn/orphans/" + id + "/cleanup", "POST", {});
      setMessage(t("Obsolete VPN connection removed; data preserved"));
      reload();
    } catch (error) {
      setFailure((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Panel title={t(appsOnly ? "App VPN connections" : "Shared VPN")}>
      <p className="muted">
        {t(
          appsOnly
            ? "Disconnect apps from the shared VPN here before uninstalling MediaVPN. MediaSeed can also be disconnected from its own VPN settings."
            : "Use one VPN profile for your apps. Local web addresses stay the same. Apps selected here have no direct internet fallback.",
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
      {!appsOnly && (
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
      )}
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
      {!!data?.orphans?.length && (
        <section className="stack">
          <h3>{t("Obsolete VPN connections")}</h3>
          <p>
            {t(
              "These apps are uninstalled, but their VPN connections remain. Remove the obsolete connections before uninstalling MediaVPN.",
            )}
          </p>
          {data.orphans.map((orphan) => (
            <div className="runtime-toolbar" key={orphan.id}>
              <strong>{orphan.name}</strong>
              <span className="muted">{orphan.hostId}</span>
              <button disabled={busy} onClick={() => void cleanup(orphan.id)}>
                {t("Remove obsolete {value0} connection", {
                  value0: orphan.name,
                })}
              </button>
            </div>
          ))}
        </section>
      )}
      <p className="muted">
        {t(
          "MediaSeed requires port forwarding on the chosen profile. Other hosts must be paired with MediaHub and able to reach the gateway over your private network.",
        )}
      </p>
    </Panel>
  );
}
