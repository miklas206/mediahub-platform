import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Download, RefreshCw } from "lucide-react";
import { api } from "./api";
import { Panel } from "./phase2";
import { ServiceIcon } from "./service-icon";
import { useData } from "./use-data";
import { t, translateText } from "./i18n";
import { NotificationPopup } from "./notification-popup";
import { OperationProgress, type OperationState } from "./operation-progress";
import "./managed-app-setup.css";

type Plan = {
  planDigest: string;
  alreadyRunning: boolean;
  operation: {
    state: string;
    message?: string;
    progress?: number;
    phase?: string;
    operationId?: string;
  };
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
  const { data: prerequisite, reload: reloadPrerequisite } = useData<{
    state: string;
    message: string | null;
  }>("/managed-install/prerequisites");
  const preparing = prerequisite?.state === "preparing";
  useEffect(() => {
    if (prerequisite?.state === "ready")
      window.dispatchEvent(new Event("apps-changed"));
  }, [prerequisite?.state]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [submitted, setSubmitted] = useState<Plan["operation"] | null>(null);
  const job =
    submitted && data?.operation.operationId !== submitted.operationId
      ? submitted
      : data?.operation;
  const running =
    busy || preparing || ["accepted", "running"].includes(job?.state || "");
  useEffect(() => {
    if (!preparing) return;
    const timer = window.setInterval(() => {
      reloadPrerequisite();
      reload();
    }, 2500);
    return () => window.clearInterval(timer);
  }, [preparing, reloadPrerequisite, reload]);
  const succeeded = !busy && job?.state === "succeeded" && data?.alreadyRunning;
  const phases = ["preparing", "containers", "health", "registering"];
  const phase = Math.max(0, phases.indexOf(job?.phase || "preparing"));
  const labels = [
    "Preparing installation",
    "Starting app containers",
    "Checking app health",
    "Registering app and hub login",
  ];
  const operation: OperationState = {
    title: t("Install {value0}", { value0: name }),
    status: busy
      ? "running"
      : job?.state === "failed"
        ? "error"
        : succeeded
          ? "success"
          : "running",
    progress: busy ? 0 : (job?.progress ?? (succeeded ? 100 : 5)),
    message: busy
      ? "Preparing installation"
      : job?.message ||
        (succeeded ? "App installed and running" : "Starting app containers"),
    steps: labels.map((label, index) => ({
      label,
      state:
        succeeded || index < phase
          ? "complete"
          : index === phase
            ? job?.state === "failed"
              ? "error"
              : "running"
            : "pending",
    })),
    details: [],
    connectionLost: !!error && running,
  };
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(reload, 3500);
    return () => window.clearInterval(timer);
  }, [running, reload]);
  useEffect(() => {
    if (succeeded) window.dispatchEvent(new Event("apps-changed"));
  }, [succeeded]);
  async function install() {
    if (!data) return;
    setBusy(true);
    setFailure("");
    setSubmitted(null);
    try {
      setSubmitted(
        await api<Plan["operation"]>(path, "POST", {
          planDigest: data.planDigest,
        }),
      );
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
        {preparing && (
          <div role="status">
            <p>{t("Preparing app prerequisites")}</p>
            <progress
              aria-label={t("Preparing app prerequisites")}
              style={{ width: "100%" }}
            />
          </div>
        )}
        {prerequisite?.state === "failed" && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              void api("/managed-install/prerequisites/retry", "POST", {})
                .then(() => reloadPrerequisite())
                .catch((error) => setFailure((error as Error).message))
                .finally(() => setBusy(false));
            }}
          >
            {t("Retry preparation")}
          </button>
        )}
        {error && !preparing && (
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
        {!preparing && (running || job?.state === "failed") && (
          <OperationProgress operation={operation} />
        )}
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
