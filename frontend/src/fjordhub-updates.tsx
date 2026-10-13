import { useConfirm } from "./confirmation-dialog";
import { t, getLocale } from "./i18n";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { NotificationPopup } from "./notification-popup";
import { ServiceIcon } from "./service-icon";
import type { Integration } from "./integrations";

export type AppInfo = {
  id: string;
  name: string;
  installed: boolean;
  port: number | null;
  icon_path: string | null;
  permissions: { updates: boolean; app_data: boolean };
};
export type UpdateStatus = {
  app_id: string;
  ok: boolean;
  state?: string;
  update_available: boolean;
  running: boolean;
  stale?: boolean;
  accepted?: boolean;
  current_rev?: string;
  remote_rev?: string;
  checked_at?: string | number;
  started_at?: string | number;
  finished_at?: string | number;
  error?: string;
};
type UpdateView = {
  app_info: Record<string, AppInfo>;
  app_info_stale: boolean;
  updates: Record<string, UpdateStatus>;
  error?: string;
  polled_at?: string;
};

export function FjordHubIcon({
  row,
  appId,
  size = 30,
}: {
  row: Integration;
  appId: string;
  size?: number;
}) {
  const info = row.snapshot.app_info?.[appId];
  const revision = `${info?.icon_path || ""}:${row.lastSuccessfulSync || ""}`;
  const [failed, setFailed] = useState("");
  if (!info?.icon_path || failed === revision)
    return <ServiceIcon packageId={appId} size={size} />;
  return (
    <img
      width={size}
      height={size}
      alt=""
      style={{ objectFit: "contain" }}
      src={`/api/v1/integrations/${encodeURIComponent(row.id)}/apps/${encodeURIComponent(appId)}/icon?v=${encodeURIComponent(revision)}`}
      onError={() => setFailed(revision)}
    />
  );
}

export function canStart(
  info: AppInfo | undefined,
  status: UpdateStatus | undefined,
  stale: boolean,
) {
  return (
    !stale &&
    info?.installed === true &&
    info.permissions.updates === true &&
    status?.ok === true &&
    !status.stale &&
    status.update_available === true &&
    status.running === false
  );
}

function statusLabel(status: UpdateStatus | undefined) {
  if (!status) return t("Status not confirmed");
  if (status.running)
    return status.stale
      ? t("Update in progress · waiting for connection")
      : t("Update in progress");
  if (status.stale) return t("Last known status · stale");
  if (!status.ok || ["failed", "error"].includes(status.state || ""))
    return t("Update failed");
  if (status.update_available) return t("Update available");
  return t("No update available");
}

function stamp(value: string | number | undefined) {
  if (value === undefined) return t("Not confirmed");
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isNaN(date.getTime())
    ? t("Not confirmed")
    : date.toLocaleString(getLocale());
}

export function FjordHubUpdates({
  row,
  administrator,
}: {
  row: Integration;
  administrator: boolean;
}) {
  const confirm = useConfirm();
  const [view, setView] = useState<UpdateView>({
    app_info: row.snapshot.app_info || {},
    app_info_stale: row.snapshot.app_info_stale ?? true,
    updates: row.snapshot.updates || {},
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const inFlight = useRef(false);
  const current = useRef(view);
  current.current = view;
  useEffect(() => {
    if (!row.enabled || !row.tokenConfigured) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      if (!inFlight.current && !document.hidden) {
        inFlight.current = true;
        try {
          const result = await api<UpdateView>(
            `/integrations/${encodeURIComponent(row.id)}/updates`,
            "GET",
            undefined,
            controller.signal,
          );
          if (!stopped) {
            current.current = result;
            setView(result);
            setError(result.error || "");
          }
        } catch (e) {
          if (!stopped) {
            setError((e as Error).message);
            setView((old) => ({
              ...old,
              app_info_stale: true,
              updates: Object.fromEntries(
                Object.entries(old.updates).map(([id, status]) => [
                  id,
                  { ...status, stale: true },
                ]),
              ),
            }));
          }
        } finally {
          inFlight.current = false;
        }
      }
      if (!stopped)
        timer = setTimeout(
          () => void poll(),
          Object.values(current.current.updates).some((s) => s.running)
            ? 5000
            : 45000,
        );
    }
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [row.id, row.enabled, row.tokenConfigured, refreshKey]);
  async function act(id: string, action: "check" | "start") {
    if (inFlight.current) return;
    if (
      action === "start" &&
      !(await confirm(
        `Start opdatering af ${view.app_info[id]?.name || id}? FjordHub kan genstarte.`,
        { title: "Install update?", confirmLabel: "Install update" },
      ))
    )
      return;
    inFlight.current = true;
    setBusy(id);
    setError("");
    if (action === "start")
      setView((old) => ({
        ...old,
        updates: {
          ...old.updates,
          [id]: {
            ...old.updates[id],
            app_id: id,
            ok: true,
            update_available: true,
            running: true,
            stale: true,
          },
        },
      }));
    try {
      const result = await api<UpdateView>(
        `/integrations/${encodeURIComponent(row.id)}/updates/${encodeURIComponent(id)}/${action}`,
        "POST",
        {},
      );
      setView(result);
      setError(result.error || "");
    } catch (e) {
      setError((e as Error).message);
      setView((old) => ({ ...old, app_info_stale: true }));
    } finally {
      setBusy("");
      inFlight.current = false;
      setRefreshKey((key) => key + 1);
    }
  }
  const metadata = { ...view.app_info, ...row.snapshot.app_info };
  const ids = [
    ...new Set([...Object.keys(metadata), ...Object.keys(view.updates)]),
  ];
  return (
    <section
      className="fjordhub-update-panel stack"
      aria-label="FjordHub-opdateringer"
    >
      <h3>{t("App information and updates")}</h3>
      <p className="muted">
        {t(" Status is checked every 45 seconds and every 5 seconds during updates. Installation starts only when you choose it. ")}</p>
      {error && <NotificationPopup tone="danger">{error}</NotificationPopup>}
      {!ids.length && (
        <p>
          {t(" App information or update access is unavailable. Enable access on the existing FjordHub token; older servers may lack API support. ")}</p>
      )}
      {ids.map((id) => {
        const info = metadata[id],
          status = view.updates[id];
        const stale =
          view.app_info_stale ||
          !!row.snapshot.app_info_stale ||
          !!row.snapshot.stale ||
          !row.enabled;
        return (
          <article className="fjordhub-update-row stack" key={id}>
            <div className="button-row">
              <FjordHubIcon
                row={{
                  ...row,
                  snapshot: { ...row.snapshot, app_info: metadata },
                }}
                appId={id}
              />
              <strong>{info?.name || id}</strong>
              <span className="badge">{statusLabel(status)}</span>
            </div>
            <small>
              {info?.installed
                ? `Installeret${info.port ? ` · Port ${info.port}` : ""}`
                : t("Installation not confirmed")}
              {!info?.permissions.updates && " · Ingen opdateringsrettighed"}
            </small>
            {status && (
              <>
                <small>
                  {t(" Installed revision: ")}{status.current_rev || t("Unknown")} {t(" · Latest revision: ")}{status.remote_rev || t("Unknown")}
                </small>
                <small>
                  {t(" Version check: ")}{stamp(status.checked_at)} {t(" · Started:")}{" "}
                  {stamp(status.started_at)} {t(" · Finished:")}{" "}
                  {stamp(status.finished_at)}
                </small>
              </>
            )}
            {status?.accepted && status.running && (
              <p role="status">
                {t(" Start accepted (202) — not finished. Waiting for a confirmed result. ")}</p>
            )}
            {administrator && info?.permissions.updates && (
              <div className="button-row">
                <button
                  disabled={
                    !!busy || stale || !info.installed || !!status?.running
                  }
                  onClick={() => void act(id, "check")}
                >
                  {t(" Check version ")}</button>
                <button
                  disabled={!!busy || !canStart(info, status, stale)}
                  onClick={() => void act(id, "start")}
                >
                  {busy === id ? t("Processing…") : t("Update app")}
                </button>
              </div>
            )}
          </article>
        );
      })}
      <small className="muted">
        {t(" Last status poll: ")}{stamp(view.polled_at)}
      </small>
    </section>
  );
}
