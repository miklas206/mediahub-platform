import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { useConfirm } from "./confirmation-dialog";
import { NotificationPopup } from "./notification-popup";
import { safeAppUrl } from "./app-uptime";
import { t } from "./i18n";

export type AppControls = {
  actions: string[];
  logs: boolean;
  updateCheck: boolean;
  updatePath?: string | null;
};
const empty: AppControls = { actions: [], logs: false, updateCheck: false };

export function StopAppButton({
  appId,
  name,
  packageId,
  running,
  onChanged,
}: {
  appId: string;
  name: string;
  packageId: string;
  running?: boolean | null;
  onChanged: () => void;
}) {
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function stop() {
    const message =
      packageId === "org.mediahub.mediavpn"
        ? t(
            "Stop MediaVPN? Apps using its VPN and public domains will lose access until it is started again.",
          )
        : t("Stop {app}? Active tasks and connections will be interrupted.", {
            app: name,
          });
    if (!(await confirm(message, { title: t("Stop {app}", { app: name }) })))
      return;
    setBusy(true);
    setError("");
    try {
      await api(`/apps/${encodeURIComponent(appId)}/actions/stop`, "POST");
      onChanged();
      window.dispatchEvent(new Event("apps-changed"));
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      {error && <NotificationPopup tone="danger">{error}</NotificationPopup>}
      <button
        className="hub-card-stop danger"
        disabled={busy || running !== true}
        aria-label={t("Stop {app}", { app: name })}
        onClick={() => void stop()}
      >
        {t(busy ? "Working..." : "Stop app")}
      </button>
    </>
  );
}

export function AppControlPanel({
  appId,
  name,
  packageId,
  controls = empty,
  openUrl,
  onChanged,
}: {
  appId?: string | null;
  name: string;
  packageId: string;
  controls?: AppControls;
  openUrl?: string | null;
  onChanged: () => void;
}) {
  const confirm = useConfirm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [logs, setLogs] = useState<
    { timestamp: number; message: string }[] | null
  >(null);
  const url = safeAppUrl(openUrl, packageId);
  async function runAction(action: string) {
    if (!appId) return;
    const message =
      action === "stop" && packageId === "org.mediahub.mediavpn"
        ? t(
            "Stop MediaVPN? Apps using its VPN and public domains will lose access until it is started again.",
          )
        : t(
            "{action} {app}? This can interrupt active tasks and connections.",
            {
              action: t(
                action === "start"
                  ? "Start"
                  : action === "stop"
                    ? "Stop"
                    : "Restart",
              ),
              app: name,
            },
          );
    if (!(await confirm(message, { title: t("Runtime controls") }))) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/apps/${encodeURIComponent(appId)}/actions/${action}`, "POST");
      setNotice(t("App runtime action completed"));
      onChanged();
      window.dispatchEvent(new Event("apps-changed"));
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function check() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ message?: string }>(
        `/apps/${encodeURIComponent(appId!)}/update-check`,
        "POST",
      );
      setNotice(result.message || t("Update check completed"));
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function showLogs() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{
        entries: { timestamp: number; message: string }[];
      }>(`/apps/${encodeURIComponent(appId!)}/logs`);
      setLogs(result.entries);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel app-control-panel">
      <div className="panel-heading">
        <h2>{t("Runtime controls")}</h2>
      </div>
      <div className="phase-content">
        <p>
          {t(
            controls.actions.length
              ? "Runtime actions use the app's verified installation. App data and media are preserved."
              : "This app is connected for monitoring. Runtime control is not available for this connection.",
          )}
        </p>
        {error && <NotificationPopup tone="danger">{error}</NotificationPopup>}
        {notice && <NotificationPopup tone="info">{notice}</NotificationPopup>}
        <div className="button-row">
          {["start", "stop", "restart"].map((action) => (
            <button
              key={action}
              disabled={busy || !appId || !controls.actions.includes(action)}
              onClick={() => void runAction(action)}
            >
              {t(
                action === "start"
                  ? "Start {app}"
                  : action === "stop"
                    ? "Stop {app}"
                    : "Restart {app}",
                { app: name },
              )}
            </button>
          ))}
        </div>
        <div className="button-row">
          {url && (
            <a
              className="button-link"
              href={url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("Open app")}
            </a>
          )}
          <button
            disabled={busy || !appId || !controls.updateCheck}
            onClick={() => void check()}
          >
            {t("Check for updates")}
          </button>
          {controls.updatePath && (
            <Link className="button-link" to={controls.updatePath}>
              {t("Update app")}
            </Link>
          )}
        </div>
        <button
          disabled={busy || !appId || !controls.logs}
          onClick={() => void showLogs()}
        >
          {t("View logs")}
        </button>
        {busy && <p role="status">{t("Working...")}</p>}
        {logs && (
          <div className="app-control-logs">
            <h3>{t("App runtime log")}</h3>
            {logs.length ? (
              logs.map((entry, index) => (
                <p key={index}>
                  {new Date(entry.timestamp * 1000).toLocaleString()} ·{" "}
                  {entry.message}
                </p>
              ))
            ) : (
              <p>{t("No retained runtime log entries")}</p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
