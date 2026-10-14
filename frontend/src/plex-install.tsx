import { translateText, t } from "./i18n";

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PlexAccountSetup } from "./plex-account-setup";
import { Film, ShieldCheck } from "lucide-react";
import { api } from "./api";
import { ErrorBox, Panel, useLoad } from "./phase2";
import {
  PlexInstallProgress,
  type PlexInstallOperation,
} from "./plex-install-progress";

type Choice = {
  id: string;
  label: string;
  kind: "movies" | "tv" | "other" | "appdata";
};
export function PlexInstallPage({ embedded = false }: { embedded?: boolean }) {
  const { data, error } = useLoad<{ hostId: string; storage: Choice[] }>(
    "/plex/install-options",
  );
  const [selected, setSelected] = useState<string[]>([]);
  const [appdata, setAppdata] = useState("");
  const [name, setName] = useState("MediaHub");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [digest, setDigest] = useState("");
  const [done, setDone] = useState(false);
  const [starting, setStarting] = useState(false);
  const status = useLoad<{ operation: PlexInstallOperation }>(
    "/plex/install-status",
  );
  const job: PlexInstallOperation | undefined =
    starting || (done && status.data?.operation.state === "idle")
      ? {
          action: "install",
          state: "running",
          phase: "preparing",
          indeterminate: true,
        }
      : status.data?.operation;
  const installing =
    starting || (job?.action === "install" && job.state === "running");
  const completed = job?.action === "install" && job.state === "succeeded";
  const statusLoaded = !!status.data;
  useEffect(() => {
    if (!done && !installing && statusLoaded) return;
    if (job?.state === "failed" || completed) return;
    const timer = window.setInterval(status.reload, 2500);
    return () => window.clearInterval(timer);
  }, [done, installing, job?.state, completed, statusLoaded, status.reload]);
  useEffect(() => {
    if (completed) window.dispatchEvent(new Event("apps-changed"));
  }, [completed]);
  const selection = (kind: string) =>
    (data?.storage || [])
      .filter((s) => s.kind === kind && selected.includes(s.id))
      .map((s) => s.id);
  const spec = () => ({
    hostId: data?.hostId || "local",
    installationId: "plex-main",
    moviesStorageIds: selection("movies"),
    tvStorageIds: selection("tv"),
    otherStorageIds: selection("other"),
    appdataStorageId: appdata,
    serverName: name,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  });
  const review = async () => {
    setBusy(true);
    setFailure("");
    try {
      setDigest(
        (
          await api<{ planDigest: string }>(
            "/plex/install-plan",
            "POST",
            spec(),
          )
        ).planDigest,
      );
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const install = async () => {
    setBusy(true);
    setStarting(true);
    setFailure("");
    try {
      await api("/plex/install", "POST", {
        installation: spec(),
        reviewedPlanDigest: digest,
      });
      setDone(true);
      window.dispatchEvent(new Event("apps-changed"));
    } catch (e) {
      setFailure((e as Error).message);
    } finally {
      setBusy(false);
      setStarting(false);
      status.reload();
    }
  };
  return (
    <div className="stack app-install-page">
      {!embedded && <Link to="/">{t("Back to MediaHub")}</Link>}
      <header>
        <p className="eyebrow">{t("YOUR MEDIA, YOUR SERVER")}</p>
        <h1>
          <Film />
          {t(" Install Plex")}
        </h1>
        <p>
          {t(
            "Choose your existing media folders. Plex reads the originals — nothing is moved or duplicated.",
          )}
        </p>
      </header>
      <ErrorBox error={error || failure || status.error} />
      <PlexInstallProgress
        job={job}
        connectionLost={!!status.error && installing}
      />
      {completed && <PlexAccountSetup />}
      {done || installing || completed ? (
        <Panel
          title={t(
            completed
              ? "Installation"
              : job?.state === "failed"
                ? "Installation needs attention"
                : "Plex is starting",
          )}
        >
          <p>
            {completed || job?.state === "failed"
              ? translateText(job.message)
              : t(
                  "Installation continues on the Agent even if this page is closed. Do not start another installation.",
                )}
          </p>
          <Link to="/">{t("Back to MediaHub")}</Link>
          {job?.state === "failed" && (
            <button
              onClick={() => {
                setDone(false);
                setDigest("");
              }}
            >
              {t("Review installation")}
            </button>
          )}
        </Panel>
      ) : (
        <>
          <Panel title={t("1 · Choose your libraries")}>
            {!data && !error && (
              <p role="status">{t("Finding approved media storage…")}</p>
            )}
            {data && !data.storage.some((s) => s.kind !== "appdata") && (
              <p>
                {t(
                  "Register your existing media storage before installing Plex.",
                )}
              </p>
            )}
            {data?.storage
              .filter((s) => s.kind !== "appdata")
              .map((s) => (
                <label className="check-label" key={s.id}>
                  <input
                    type="checkbox"
                    checked={selected.includes(s.id)}
                    disabled={busy}
                    onChange={(e) => {
                      setSelected(
                        e.target.checked
                          ? [...selected, s.id]
                          : selected.filter((i) => i !== s.id),
                      );
                      setDigest("");
                    }}
                  />
                  {s.label}{" "}
                  <small>
                    {" "}
                    · {s.kind === "tv" ? t("TV shows") : translateText(s.kind)}
                    {t(" · read only")}
                  </small>
                </label>
              ))}
          </Panel>
          <Panel title={t("2 · Server settings")}>
            <div className="dynamic-form">
              <label>
                {t("Server name")}
                <input
                  value={name}
                  maxLength={80}
                  disabled={busy}
                  onChange={(e) => {
                    setName(e.target.value);
                    setDigest("");
                  }}
                />
              </label>
              <label>
                {t("App data storage")}
                <select
                  value={appdata}
                  disabled={busy}
                  onChange={(e) => {
                    setAppdata(e.target.value);
                    setDigest("");
                  }}
                >
                  <option value="">{t("Choose dedicated app storage")}</option>
                  {data?.storage
                    .filter((s) => s.kind === "appdata")
                    .map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.label}
                      </option>
                    ))}
                </select>
              </label>
            </div>
            <p>
              {t(
                "Link your Plex account in the next step, after the server has finished installing.",
              )}
            </p>
          </Panel>
          <Panel title={t("3 · Review and install")}>
            <p>
              <ShieldCheck size={18} />
              {t(
                " Media stays read-only. Account preferences are encrypted at rest. No router ports or public access are configured.",
              )}
            </p>
            {digest ? (
              <>
                <p>
                  {t(
                    "Storage and installation plan validated. The server will re-check the disk before starting.",
                  )}
                </p>
                <button className="primary" disabled={busy} onClick={install}>
                  {busy ? t("Installing Plex…") : t("Install Plex")}
                </button>
              </>
            ) : (
              <button
                disabled={busy || !selected.length || !appdata || !name.trim()}
                onClick={review}
              >
                {busy ? t("Checking…") : t("Review installation")}
              </button>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
