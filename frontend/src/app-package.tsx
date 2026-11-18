import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { getLocale, t } from "./i18n";
import { NotificationPopup } from "./notification-popup";
import { usePageSnapshot } from "./use-service-snapshot";
import { useConfirm } from "./confirmation-dialog";

type App = "plex-gpu-transcoder" | "mediaupload" | "video-downloader";
const names = {
  "plex-gpu-transcoder": "Plex GPU Transcoder",
  mediaupload: "MediaUpload",
  "video-downloader": "Video Downloader",
};
type Status = {
  firstLogin?: boolean;
  url?: string;
  available: boolean;
  state: string;
  version?: string;
  message?: string;
  operationId?: string;
};
type Location = {
  id: string;
  label: string;
  ready: boolean;
  readOnly?: boolean;
};

export function PackageSetup({
  app,
  installed = false,
}: {
  app: App;
  installed?: boolean;
}) {
  const endpoint = "/app-packages/" + app;
  const state = usePageSnapshot<Status>(endpoint, 3000);
  const confirm = useConfirm();
  const [location, setLocation] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [login, setLogin] = useState<{
    setupUrl?: string;
    username?: string;
    password?: string;
  }>({});
  const [operation, setOperation] = useState("");
  const inProgress = ["queued", "running"].includes(state.data?.state || "");
  const complete = state.data?.state === "succeeded";
  async function install() {
    if (
      !(await confirm(
        t("Wait for active jobs or playback to finish before continuing."),
        { title: t("Install or update {name}", { name: names[app] }) },
      ))
    )
      return;
    setSending(true);
    setError("");
    try {
      const result = await api<{ operationId: string }>(endpoint, "POST", {
        location,
      });
      setOperation(result.operationId);
      state.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  }
  async function firstLogin() {
    try {
      setLogin(await api(endpoint + "/first-login", "POST"));
      state.reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const url =
    state.data?.url && state.data.url.startsWith("https://")
      ? state.data.url
      : "";
  return (
    <section className="panel stack">
      {app !== "plex-gpu-transcoder" && <h1>{names[app]}</h1>}
      {app !== "plex-gpu-transcoder" && (
        <PackageStorage app={app} value={location} onChange={setLocation} />
      )}
      <div className="assisted-actions">
        {state.data?.available && (
          <button
            type="button"
            className="primary"
            disabled={sending || inProgress}
            onClick={install}
          >
            {inProgress || sending
              ? t("Installation in progress")
              : t(
                  installed || complete
                    ? "Update app"
                    : "Install or update {name}",
                  { name: names[app] },
                )}
          </button>
        )}
        <a
          href={`https://github.com/miklas206/mediahub-app-releases/blob/main/apps/${app}${getLocale().startsWith("da") ? ".da" : ""}.md`}
          target="_blank"
          rel="noopener noreferrer"
        >
          {t("Package and installation guide")}
        </a>
      </div>
      {state.data && !state.data.available && (
        <p>{t("Update the Linux MediaHub host to enable app installation.")}</p>
      )}
      {inProgress && (
        <p role="status">
          {t("The host is checking the package and preparing the app.")}
        </p>
      )}
      {state.data?.firstLogin && !login.password && !login.setupUrl && (
        <button type="button" onClick={firstLogin}>
          {t("Show first login details")}
        </button>
      )}
      {login.password && (
        <p>
          {t("Username")}: <strong>{login.username}</strong> · {t("Password")}:{" "}
          <code>{login.password}</code>
        </p>
      )}
      {login.setupUrl && url && login.setupUrl.startsWith(url + "/#setup=") ? (
        <a href={login.setupUrl} target="_blank" rel="noreferrer">
          {t("Set up your login")}
        </a>
      ) : url ? (
        <a href={url} target="_blank" rel="noreferrer">
          {t("Open app")}
        </a>
      ) : null}
      {complete && (
        <p>
          {t("Installed version: {version}", {
            version: state.data?.version || "—",
          })}
        </p>
      )}
      {complete && operation && operation === state.data?.operationId && (
        <NotificationPopup tone="success">
          {t("Installation completed")}
        </NotificationPopup>
      )}
      {(state.data?.state === "failed" || error || state.error) && (
        <NotificationPopup tone="danger">
          {t(
            error ||
              state.error ||
              state.data?.message ||
              "Installation failed",
          )}
        </NotificationPopup>
      )}
    </section>
  );
}
function PackageStorage({
  app,
  value,
  onChange,
}: {
  app: App;
  value: string;
  onChange: (id: string) => void;
}) {
  const { data } = usePageSnapshot<{ locations: Location[] }>(
    "/storage-control",
  );
  const locations = (data?.locations || []).filter(
    (row) => row.ready && (app !== "video-downloader" || !row.readOnly),
  );
  return (
    <div>
      <label>
        {t(
          app === "mediaupload" ? "Read-only media library" : "Download folder",
        )}
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">
            {t(
              "Keep existing settings, or select a folder for first installation",
            )}
          </option>
          {locations.map((row) => (
            <option key={row.id} value={row.id}>
              {row.label}
            </option>
          ))}
        </select>
      </label>
      {!locations.length && (
        <Link to="/settings?section=Storage">{t("Manage storage")}</Link>
      )}
    </div>
  );
}
