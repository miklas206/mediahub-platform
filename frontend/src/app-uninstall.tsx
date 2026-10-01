import { useEffect, useState } from "react";
import { api } from "./api";
import type { AppInfo } from "./contracts";
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
  app: AppInfo;
  onRemoved: () => void;
}) {
  const [open, setOpen] = useState(app.state === "removing");
  const [status, setStatus] = useState<Removal>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
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
              " Check the Agent connection and update the Agent if removal is not supported.",
          );
      }
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [open, endpoint, onRemoved, busy]);
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
        {app.packageId === "org.mediahub.cloudflared"
          ? "Remove monitoring"
          : "Uninstall"}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label={`Remove ${app.name}`}
          className="app-removal-dialog"
        >
          <h3>
            {app.packageId === "org.mediahub.cloudflared"
              ? "Remove monitoring"
              : "Uninstall"}{" "}
            {app.name}
          </h3>
          <p>
            {status?.message ||
              "Checking installation identity and removal support..."}
          </p>
          <p>
            Media files and app data will be kept. This does not free space used
            by downloads or libraries.
          </p>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {working && (
            <p role="status">
              Removing runtime on the server... You can leave this page and
              return.
            </p>
          )}
          <div className="runtime-toolbar">
            <button
              disabled={working || !status?.installationId || !!error}
              onClick={() => void remove()}
            >
              Confirm removal
            </button>
            <button onClick={() => setOpen(false)}>
              {working ? "Close" : "Cancel"}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
