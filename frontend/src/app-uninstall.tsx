import { translateText, t, useLanguage } from "./i18n";
import { NotificationPopup } from "./notification-popup";

import { createPortal } from "react-dom";
import { useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { OperationProgress, type OperationState } from "./operation-progress";
import { api } from "./api";
import { Link } from "react-router-dom";
import type { InstalledAppInfo } from "./contracts";
type Removal = {
  state: string;
  progress?: number;
  phase?: string;
  installationId?: string;
  mode?: string;
  message?: string;
  configurationPath?: string;
};
export function AppUninstall({
  app,
  onRemoved,
  buttonClassName,
  showIcon = false,
}: {
  app: InstalledAppInfo;
  onRemoved: () => void;
  buttonClassName?: string;
  showIcon?: boolean;
}) {
  useLanguage();
  const [open, setOpen] = useState(app.state === "removing");
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!open) return;
    const element = dialog.current!;
    const opener = document.activeElement as HTMLElement | null;
    element.showModal();
    element.querySelector<HTMLButtonElement>(".app-removal-cancel")?.focus();
    return () => { element.close(); if (opener?.isConnected) opener.focus(); };
  }, [open]);
  const [status, setStatus] = useState<Removal>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const windowsShare = app.packageId === "org.mediahub.windows-share";
  const managed = ["org.mediahub.mediaseed", "org.mediahub.mediavpn"].includes(app.packageId);
  const removalLabel = windowsShare
    ? t("Remove connection")
    : app.packageId === "org.mediahub.cloudflared"
      ? t("Remove monitoring")
      : t("Uninstall");
  const endpoint = `/apps/${app.id}/uninstall`;
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const result = await api<Removal>(endpoint);
        if (cancelled) return;
        setStatus(result);
        setError("");
        if (result.state === "succeeded") {
          setOpen(false);
          onRemoved();
          return;
        }
        if (["accepted", "running"].includes(result.state))
          timer = setTimeout(() => void poll(), 2000);
      } catch (e) {
        if (!cancelled) {
          setError(
            (e as Error).message +
              (managed ? "" : windowsShare
                ? " Check the connection to MediaHub and try again."
                : " Check the Agent connection and update the Agent if removal is not supported."),
          );
          timer = setTimeout(() => void poll(), 2500);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, endpoint, onRemoved, busy, windowsShare, managed]);
  const remove = async () => {
    if (!status?.installationId) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Removal>(endpoint, "POST", {
        confirmedInstallationId: status.installationId,
      });
      setStatus(result);
      if (result.state === "succeeded") {
        setOpen(false);
        onRemoved();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const working = busy || ["accepted", "running"].includes(status?.state || "");
  const phase = ["preparing", "removing", "verifying"].indexOf(status?.phase || "preparing");
  const operation: OperationState = {
    title: `${removalLabel} ${translateText(app.name)}`,
    status: status?.state === "failed" ? "error" : "running",
    progress: busy ? 0 : status?.progress ?? 0,
    indeterminate: !busy && typeof status?.progress !== "number",
    message: status?.state === "failed" ? status.message || "Removal could not be verified." : t("Removing runtime on the server... You can leave this page and return."),
    steps: typeof status?.progress === "number" ? ["Checking ownership", "Stopping and removing containers", "Checking preserved data"].map((label, index) => ({
      label, state: index < phase ? "complete" : index > phase ? "pending" : status?.state === "failed" ? "error" : "running",
    })) : [],
    details: [],
    connectionLost: !!error && working,
  };
  return (
    <>
      <button
        type="button"
        className={buttonClassName}
        aria-label={`${removalLabel}: ${translateText(app.name)}`}
        onClick={() => {
          setError("");
          setStatus(undefined);
          setOpen(true);
        }}
      >
        {showIcon && <Trash2 size={15} aria-hidden="true" />}
        {removalLabel}
      </button>
      {open && createPortal(
        <dialog
          ref={dialog}
          onCancel={(event) => { event.preventDefault(); setOpen(false); }}
          aria-label={t("Remove {value0}", { value0: translateText(app.name) })}
          className="app-removal-dialog"
        >
          <h3>
            {removalLabel} {translateText(app.name)}
          </h3>
          <p>
            {translateText(status?.message) ||
              t("Checking installation identity and removal support...")}
          </p>
          {status?.state === "blocked" && status.configurationPath && (
            <Link className="button-link" to={status.configurationPath} onClick={() => setOpen(false)}>
              {t("Manage app VPN connections")}
            </Link>
          )}
          <p>
            {windowsShare
              ? t(
                  "Only the connection saved in MediaHub is removed. Shared folders, files and mapped Windows drives stay in place.",
                )
              : t(
                  "Media files and app data will be kept. This does not free space used by downloads or libraries.",
                )}
          </p>
          {error && (
            <NotificationPopup tone="danger">
              {translateText(error)}
            </NotificationPopup>
          )}
          {status?.state === "failed" && !error && (
            <NotificationPopup tone="danger">
              {translateText(status.message)}
            </NotificationPopup>
          )}
          {(working || status?.state === "failed") && (
            <OperationProgress operation={operation} />
          )}
          <div className="runtime-toolbar">
            <button
              disabled={working || !status?.installationId || !!error}
              onClick={() => void remove()}
            >
              {t("Confirm removal")}
            </button>
            <button className="app-removal-cancel" onClick={() => setOpen(false)}>
              {working ? t("Close") : t("Cancel")}
            </button>
          </div>
        </dialog>, document.body
      )}
    </>
  );
}
