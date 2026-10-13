import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Download, RefreshCw } from "lucide-react";
import { api } from "./api";
import { Panel } from "./phase2";
import { ServiceIcon } from "./service-icon";
import { useData } from "./use-data";
import { t, translateText } from "./i18n";
import { NotificationPopup } from "./notification-popup";
import "./managed-app-setup.css";

type Plan = {
  planDigest: string;
  alreadyRunning: boolean;
  operation: { state: string; message?: string };
};
export function ManagedAppInstallPage({
  kind,
}: {
  kind: "mediaseed" | "mediavpn";
}) {
  const name = kind === "mediaseed" ? "MediaSeed" : "MediaVPN";
  const packageId = `org.mediahub.${kind}`;
  const path = `/managed-install/${packageId}`;
  const { data, error, reload } = useData<Plan>(path);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const running =
    busy || ["accepted", "running"].includes(data?.operation.state || "");
  const succeeded = data?.operation.state === "succeeded";
  useEffect(() => {
    if (!running) return;
    const timer = window.setTimeout(reload, 2500);
    return () => window.clearTimeout(timer);
  }, [running, reload, data]);
  useEffect(() => {
    if (succeeded) window.dispatchEvent(new Event("apps-changed"));
  }, [succeeded]);
  async function install() {
    if (!data) return;
    setBusy(true);
    setFailure("");
    try {
      await api(path, "POST", { planDigest: data.planDigest });
      reload();
    } catch (error) {
      setFailure((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="stack managed-app-setup">
      <h2 className="managed-app-title">
        <ServiceIcon packageId={packageId} />
        {name}
      </h2>
      <Panel
        title={t(
          kind === "mediaseed"
            ? "Independent Seedbox app"
            : "Independent VPN app",
        )}
      >
        <p>
          {t(
            kind === "mediaseed"
              ? "Install MediaSeed to manage torrents, RSS feeds and tracker accounts. Downloads stay blocked until a VPN connection is verified."
              : "MediaVPN manages WireGuard profiles, server selection and port forwarding. MediaSeed only uses MediaVPN when you select it in MediaSeed.",
          )}
        </p>
        <p>
          {t(
            "Install the app on this MediaHub host. Existing accounts, settings, VPN profiles and downloads are preserved. Hub login and your theme are available in the app.",
          )}
        </p>
        {error && (
          <NotificationPopup tone="danger">
            {translateText(error)}
          </NotificationPopup>
        )}
        {failure && (
          <NotificationPopup tone="danger">
            {translateText(failure)}
          </NotificationPopup>
        )}
        {data?.operation.state === "failed" && (
          <NotificationPopup tone="danger">
            {translateText(
              data.operation.message ||
                "App installation failed; app data was preserved",
            )}
          </NotificationPopup>
        )}
        {running && (
          <p role="status">
            {t(
              "Starting app containers. You can leave this page and return to follow progress.",
            )}
          </p>
        )}
        {succeeded && <p role="status">{t("App installed and running")}</p>}
        <div className="button-row">
          <button
            className="primary"
            type="button"
            disabled={!data || running}
            onClick={() => void install()}
          >
            <Download size={16} />
            {t(
              data?.alreadyRunning
                ? "Verify app installation"
                : "Install {value0}",
              { value0: name },
            )}
          </button>
          <button type="button" disabled={running} onClick={reload}>
            <RefreshCw size={16} />
            {t("Refresh")}
          </button>
          {(succeeded || data?.alreadyRunning) && (
            <Link className="managed-app-guide" to="/">
              {t("Back to apps")}
            </Link>
          )}
        </div>
      </Panel>
    </div>
  );
}
