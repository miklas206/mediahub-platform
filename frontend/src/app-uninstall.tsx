import { translateText, t } from "./i18n";

import { useEffect, useState } from "react";
import { api } from "./api";
import type { InstalledAppInfo } from "./contracts";
type Removal = {
  state: string;
  installationId?: string;
  mode?: string;
  message?: string;
};
export function AppUninstall({
  app,
  onRemoved,
}: {
  app: InstalledAppInfo;
  onRemoved: () => void;
}) {
  const [open, setOpen] = useState(app.state === "removing");
  const [status, setStatus] = useState<Removal>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const windowsShare = app.packageId === "org.mediahub.windows-share";
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
        if (result.state === "succeeded") {
          setOpen(false);
          onRemoved();
          return;
        }
        if (["accepted", "running"].includes(result.state))
          timer = setTimeout(() => void poll(), 2000);
      } catch (e) {
        if (!cancelled)
          setError(
            (e as Error).message +
              (windowsShare
                ? " Check the connection to MediaHub and try again."
                : " Check the Agent connection and update the Agent if removal is not supported."),
          );
      }
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, endpoint, onRemoved, busy, windowsShare]);
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
  return (
    <>
      <button
        onClick={() => {
          setError("");
          setOpen(true);
        }}
      >
        {removalLabel}
      </button>
      {open && (
        <div
          role="dialog"
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
            <p role="alert" className="error">
              {translateText(error)}
            </p>
          )}
          {working && (
            <p role="status">
              {t(
                "Removing runtime on the server... You can leave this page and return.",
              )}
            </p>
          )}
          <div className="runtime-toolbar">
            <button
              disabled={working || !status?.installationId || !!error}
              onClick={() => void remove()}
            >
              {t("Confirm removal")}
            </button>
            <button onClick={() => setOpen(false)}>
              {working ? t("Close") : t("Cancel")}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
