import { useEffect, useState, type FormEvent } from "react";
import { HardDrive } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { t } from "./i18n";
import { NotificationPopup } from "./notification-popup";
import { useConfirm } from "./confirmation-dialog";
import "./storage-settings.css";

export type AppStorageInventory = {
  available: boolean;
  message?: string;
  nas: { id: string; label: string; ready: boolean; readOnly: boolean }[];
  apps?: {
    bindings: {
      app: string;
      storageId: string;
      path: string;
      readOnly: boolean;
    }[];
    interrupted: boolean;
  };
};

export function AppStorageForm({
  app,
  data,
  busy,
  change,
}: {
  app: "mediaseed" | "plex";
  data: AppStorageInventory;
  busy: boolean;
  change: (app: string, identifier: string, attach: boolean) => Promise<void>;
}) {
  const [selected, setSelected] = useState("");
  const bindings = data.apps?.bindings.filter((row) => row.app === app) || [];
  const name = app === "plex" ? "Plex" : "MediaSeed";
  const canAttach = data.nas.some(
    (row) =>
      row.id === selected &&
      row.ready &&
      (app === "plex" || !row.readOnly) &&
      !bindings.some((binding) => binding.storageId === row.id),
  );
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (canAttach) void change(app, selected, true);
  };
  return (
    <article className="storage-location app-storage-form">
      <h3>{name}</h3>
      <p className="muted">
        {t(
          app === "plex"
            ? "Stop Plex in MediaHub before changing storage. Start it again afterwards."
            : "Stop MediaSeed and MediaVPN in MediaHub before changing storage. Start MediaVPN, then MediaSeed afterwards.",
        )}
      </p>
      <p>
        {t(
          app === "plex"
            ? "Plex gets read-only access. Add the displayed folder to a library in Plex."
            : "MediaSeed gets read and write access. The NAS becomes a choice when adding torrents and RSS feeds.",
        )}
      </p>
      {app === "mediaseed" && (
        <p className="muted">
          {t(
            "In an LXC, active torrent files use a write cache on approved local media storage, never the system disk. Active files must fit there; completed, closed files are uploaded to the NAS.",
          )}
        </p>
      )}
      {bindings.map((row) => (
        <div className="app-storage-binding" key={row.storageId}>
          <strong>
            {data.nas.find((nas) => nas.id === row.storageId)?.label ||
              row.storageId}
          </strong>
          <code>{row.path}</code>
          <span className="muted">
            {t(row.readOnly ? "Read-only access" : "Read and write access")}
          </span>
          <button
            type="button"
            disabled={busy || data.apps?.interrupted}
            onClick={() => void change(app, row.storageId, false)}
          >
            {t("Remove from app")}
          </button>
        </div>
      ))}
      {app === "plex" && bindings.length > 0 && (
        <details className="storage-guide">
          <summary>{t("Use this folder in Plex")}</summary>
          <ol>
            <li>{t("Open Plex and go to Settings, Manage, Libraries.")}</li>
            <li>
              {t(
                "Add a library or edit an existing library, then choose Add folders.",
              )}
            </li>
            <li>
              {t(
                "Browse to the displayed path above and select the folder containing your movies or series.",
              )}
            </li>
            <li>
              {t("Save the library. Plex will scan the selected folder.")}
            </li>
          </ol>
        </details>
      )}
      <form className="stack" onSubmit={submit}>
        <label>
          {t("NAS storage")}
          <select
            aria-label={t("NAS storage")}
            required
            value={selected}
            disabled={busy || !data.apps || data.apps.interrupted}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="">{t("Choose NAS storage")}</option>
            {data.nas.map((row) => (
              <option
                key={row.id}
                value={row.id}
                disabled={
                  !row.ready ||
                  (app === "mediaseed" && row.readOnly) ||
                  bindings.some((binding) => binding.storageId === row.id)
                }
              >
                {row.label}
                {!row.ready
                  ? ` · ${t("Disconnected")}`
                  : app === "mediaseed" && row.readOnly
                    ? ` · ${t("Read-only access")}`
                    : ""}
              </option>
            ))}
          </select>
        </label>
        <button
          className="primary"
          disabled={busy || !canAttach || !data.apps || data.apps.interrupted}
        >
          {busy ? t("Working…") : t("Attach storage")}
        </button>
      </form>
      <Link className="text-link" to={`/app-settings/org.mediahub.${app}`}>
        {t("Open app settings")}
      </Link>
    </article>
  );
}

export function AppStorageSettings({ packageId }: { packageId?: string }) {
  const [data, setData] = useState<AppStorageInventory>();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ error: boolean; text: string }>();
  const confirm = useConfirm();
  const app = packageId?.replace("org.mediahub.", "");
  const supported = !packageId || app === "mediaseed" || app === "plex";
  useEffect(() => {
    if (!supported) return;
    const controller = new AbortController();
    const load = () =>
      api<AppStorageInventory>(
        "/storage-control",
        "GET",
        undefined,
        controller.signal,
      )
        .then(setData)
        .catch((error: Error) => {
          if (!controller.signal.aborted)
            setNotice({ error: true, text: t(error.message) });
        });
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 15000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [supported]);
  if (!supported) return null;
  const change = async (
    selectedApp: string,
    identifier: string,
    attach: boolean,
  ) => {
    if (
      !(await confirm(
        t(
          attach
            ? "Attach this NAS to the stopped app? Existing files stay where they are."
            : "Remove this NAS from the stopped app? Files on the NAS are kept.",
        ),
      ))
    )
      return;
    setBusy(true);
    setNotice(undefined);
    try {
      await api(
        `/storage-control/apps/${selectedApp}/${identifier}`,
        attach ? "POST" : "DELETE",
      );
      setData(await api<AppStorageInventory>("/storage-control"));
      setNotice({
        error: false,
        text: t("App storage saved. Start the app again to use it."),
      });
    } catch (error) {
      setNotice({ error: true, text: t((error as Error).message) });
    } finally {
      setBusy(false);
    }
  };
  const recover = async () => {
    if (
      !(await confirm(
        t(
          "Restore the previous storage attachment? Keep the apps stopped. NAS files will be kept.",
        ),
      ))
    )
      return;
    setBusy(true);
    setNotice(undefined);
    try {
      await api("/storage-control/apps/recover", "POST");
      setData(await api<AppStorageInventory>("/storage-control"));
      setNotice({
        error: false,
        text: t(
          "Previous storage attachment restored. You can start the apps again.",
        ),
      });
    } catch (error) {
      setNotice({ error: true, text: t((error as Error).message) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel app-storage-settings">
      <h2>
        <HardDrive size={19} /> {t("NAS storage for apps")}
      </h2>
      <p className="muted">
        {t(
          "Attach extra storage without moving existing downloads, media or app settings.",
        )}
      </p>
      {notice && (
        <NotificationPopup tone={notice.error ? "danger" : "success"}>
          {notice.text}
        </NotificationPopup>
      )}
      {!data && <p role="status">{t("Loading…")}</p>}
      {data && (!data.available || !data.apps) && (
        <p>
          {t(
            data.message ||
              "Update MediaHub and prepare storage on this server to attach NAS storage to apps.",
          )}
        </p>
      )}
      {data?.apps?.interrupted && (
        <div className="stack">
          <p role="alert">
            {t(
              "The storage change was interrupted. Keep the apps stopped and restore the previous attachment here.",
            )}
          </p>
          <button disabled={busy} onClick={() => void recover()}>
            {t("Restore previous attachment")}
          </button>
        </div>
      )}
      {data?.available && data.apps && (
        <div className={packageId ? "stack" : "storage-columns"}>
          {(!app || app === "mediaseed") && (
            <AppStorageForm
              app="mediaseed"
              data={data}
              busy={busy}
              change={change}
            />
          )}
          {(!app || app === "plex") && (
            <AppStorageForm
              app="plex"
              data={data}
              busy={busy}
              change={change}
            />
          )}
        </div>
      )}
    </section>
  );
}
