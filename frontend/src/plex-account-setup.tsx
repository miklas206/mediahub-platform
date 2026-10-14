import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "./api";
import { useData } from "./use-data";
import { t } from "./i18n";
import { NotificationPopup } from "./notification-popup";

type Account = {
  claimed: boolean | null;
  openUrl?: string | null;
  operation: { state: string; message: string };
};
export function PlexAccountSetup() {
  const { data, error, reload } = useData<Account>("/plex/account");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const previouslyClaimed = useRef<boolean | null | undefined>(undefined);
  const [showConfigurationPrompt, setShowConfigurationPrompt] = useState(false);
  useEffect(() => {
    if (previouslyClaimed.current === false && data?.claimed === true) {
      setShowConfigurationPrompt(true);
    }
    if (data?.claimed != null) previouslyClaimed.current = data.claimed;
  }, [data?.claimed]);
  const running = busy || data?.operation.state === "running";
  useEffect(() => {
    if (data?.claimed === true && !running) return;
    const timer = setInterval(() => {
      if (!document.hidden) reload();
    }, 5000);
    return () => clearInterval(timer);
  }, [reload, data?.claimed, running]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure("");
    try {
      await api("/plex/account", "POST", { claimToken: token.trim() });
      reload();
    } catch (error) {
      setFailure((error as Error).message);
    } finally {
      setToken("");
      setBusy(false);
    }
  }
  return (
    <section className="panel plex-account-setup">
      <h2>{t("Link Plex to your account")}</h2>
      {(error || failure) && (
        <NotificationPopup tone="danger">{failure || error}</NotificationPopup>
      )}
      {data?.claimed === true ? (
        <>
          <p role="status">{t("Plex is linked to your account")}</p>
          <p>{t("Open Plex to finish setup and add your media libraries.")}</p>
          {showConfigurationPrompt && (
            <NotificationPopup tone="success">
              <p>{t("Plex is linked to your account")}</p>
              <p>
                {t("Open Plex to finish setup and add your media libraries.")}
              </p>
              {data.openUrl && (
                <a
                  className="button"
                  href={data.openUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t("Open Plex for configuration")}
                </a>
              )}
            </NotificationPopup>
          )}
          {data.openUrl && (
            <a href={data.openUrl} target="_blank" rel="noopener noreferrer">
              {t("Open Plex for configuration")}
            </a>
          )}
        </>
      ) : (
        <>
          <p>
            {t(
              "Finish account setup here after installation. MediaHub links the server from its own network, including when it uses MediaVPN.",
            )}
          </p>
          <ol>
            <li>
              <a
                href="https://www.plex.tv/claim/"
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("Get a fresh claim token from Plex")}
              </a>
            </li>
            <li>
              {t(
                "Paste the token below and link this server. The token is short-lived; get it only when you are ready.",
              )}
            </li>
          </ol>
          <form
            className="settings-form"
            onSubmit={(event) => void submit(event)}
          >
            <label>
              {t("Plex claim token")}
              <input
                type="password"
                autoComplete="off"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                minLength={12}
                maxLength={256}
                required
                disabled={running}
              />
            </label>
            <button
              type="submit"
              disabled={
                running ||
                data?.claimed !== false ||
                !token.trim().startsWith("claim-")
              }
            >
              {t(
                running ? "Linking Plex to your account" : "Link Plex account",
              )}
            </button>
          </form>
          <p className="muted">
            {t(
              "Plex restarts briefly to apply the token. Media and VPN settings are preserved. The token is cleared after the attempt.",
            )}
          </p>
          <p role="status">
            {data
              ? t(
                  data.operation.state === "idle"
                    ? "Plex account setup is required"
                    : data.operation.message,
                )
              : t("Checking Plex account status...")}
          </p>
        </>
      )}
    </section>
  );
}
