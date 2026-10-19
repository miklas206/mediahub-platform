import { useCallback, useEffect, useState, type FormEvent } from "react";
import { HardDrive, Network, FolderOpen, RefreshCw, Copy } from "lucide-react";
import { AppStorageSettings } from "./app-storage";
import { api } from "./api";
import { bytes } from "./format";
import { t } from "./i18n";
import { NotificationPopup } from "./notification-popup";
import { useConfirm } from "./confirmation-dialog";
import "./storage-settings.css";

type Location = {
  id: string;
  label: string;
  source: string;
  kind: string;
  ready: boolean;
  readOnly?: boolean;
  totalBytes: number | null;
  freeBytes: number | null;
};
type Nas = {
  id: string;
  label: string;
  server: string;
  share: string;
  username: string;
  readOnly: boolean;
  ready: boolean;
  enabled: boolean;
  error?: string;
  path: string;
  writeCachePath?: string | null;
};
export type StorageShare = {
  name: string;
  storageId: string;
  readOnly: boolean;
  unc: string;
  username: string;
};
type Inventory = {
  available: boolean;
  message?: string;
  prerequisite?: string;
  server?: string;
  locations: Location[];
  nas: Nas[];
  shares: StorageShare[];
  passwordConfigured?: boolean;
  smbRunning?: boolean;
};

function StorageLocations({ locations }: { locations: Location[] }) {
  const roots = locations.filter(
    (row) => row.kind === "local" && row.id.startsWith("media-root-"),
  );
  const parent = (row: Location) =>
    row.kind === "local" && !roots.includes(row)
      ? roots
          .filter((root) =>
            row.source.startsWith(root.source.replace(/\/$/, "") + "/"),
          )
          .sort((a, b) => b.source.length - a.source.length)[0]
      : undefined;
  return (
    <div className="storage-locations">
      {locations
        .filter((row) => !parent(row))
        .map((row) => {
          const children = locations.filter(
            (child) => parent(child)?.id === row.id,
          );
          return (
            <article className="storage-location" key={row.id}>
              <strong>{t(row.label)}</strong>
              <span className={row.ready ? "status-ready" : "muted"}>
                {t(row.ready ? "Connected" : "Disconnected")}
              </span>
              <code>{row.source}</code>
              <span>
                {row.ready && row.freeBytes !== null && row.totalBytes !== null
                  ? `${bytes(row.freeBytes)} / ${bytes(row.totalBytes)} ${t("free")}`
                  : t("Capacity unavailable")}
              </span>
              {children.length > 0 && (
                <div className="storage-subfolders">
                  <p className="muted">
                    {t("Subfolders share the storage space shown above.")}
                  </p>
                  <ul>
                    {children.map((child) => (
                      <li key={child.id}>
                        <FolderOpen size={16} aria-hidden="true" />
                        <div>
                          <strong>{t(child.label)}</strong>
                          <code>
                            {child.source.slice(
                              row.source.replace(/\/$/, "").length + 1,
                            )}
                          </code>
                        </div>
                        {!child.ready && (
                          <span className="muted">{t("Disconnected")}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </article>
          );
        })}
    </div>
  );
}

export function WindowsDriveGuide({ share }: { share: StorageShare }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  return (
    <details className="storage-guide">
      <summary>{t("Connect this folder in Windows")}</summary>
      {copied && (
        <NotificationPopup tone="success">
          {t("Network path copied")}
        </NotificationPopup>
      )}
      {error && <NotificationPopup tone="danger">{error}</NotificationPopup>}
      <p className="storage-unc">
        <code>{share.unc}</code>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard
              .writeText(share.unc)
              .then(() => {
                setCopied(false);
                queueMicrotask(() => setCopied(true));
              })
              .catch(() =>
                setError(t("Copy the displayed network path manually")),
              );
          }}
          aria-label={t("Copy network path")}
        >
          <Copy size={16} />
        </button>
      </p>
      <ol>
        <li>{t("Connect your PC to the same home network as MediaHub.")}</li>
        <li>
          {t(
            "Open File Explorer, right-click This PC and choose Map network drive.",
          )}
        </li>
        <li>
          {t("Choose an unused drive letter and paste the network path above.")}
        </li>
        <li>
          {t(
            "Select Reconnect at sign-in and Connect using different credentials.",
          )}
        </li>
        <li>
          {t(
            "Use the username below and the Windows sharing password you created here.",
          )}{" "}
          <strong>{share.username}</strong>
        </li>
      </ol>
      <p className="muted">
        {t(
          "Your MediaHub login and NAS password are separate from the Windows sharing password.",
        )}
      </p>
      <p className="muted">
        {t(
          "If Windows reports multiple credentials, close files on this server and remove only its old connection in Credential Manager. Other mapped drives can stay connected.",
        )}
      </p>
    </details>
  );
}

export function StorageSettings() {
  const [data, setData] = useState<Inventory>();
  const [notice, setNotice] = useState<{ text: string; error: boolean }>();
  const [busy, setBusy] = useState(false);
  const [nas, setNas] = useState({
    label: "",
    server: "",
    share: "",
    username: "",
    password: "",
    readOnly: true,
  });
  const [share, setShare] = useState({
    name: "MediaHub",
    storageId: "",
    password: "",
    readOnly: true,
  });
  const [password, setPassword] = useState("");
  const confirm = useConfirm();
  const refresh = useCallback(async () => {
    setData(await api<Inventory>("/storage-control"));
  }, []);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const load = async () => {
      try {
        const value = await api<Inventory>(
          "/storage-control",
          "GET",
          undefined,
          controller.signal,
        );
        if (active) setData(value);
      } catch (error) {
        if (active) setNotice({ text: (error as Error).message, error: true });
      }
    };
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 10000);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);
  const run = async (
    path: string,
    method = "POST",
    body?: unknown,
    done?: () => void,
  ) => {
    setBusy(true);
    setNotice(undefined);
    try {
      await api("/storage-control" + path, method, body);
      done?.();
      setNotice({ text: t("Storage operation completed"), error: false });
    } catch (error) {
      setNotice({ text: (error as Error).message, error: true });
    } finally {
      try {
        await refresh();
      } catch {
        /* Preserve the operation result; polling retries the read. */
      }
      setBusy(false);
    }
  };
  const addNas = (event: FormEvent) => {
    event.preventDefault();
    void run("/nas", "POST", nas, () =>
      setNas((current) => ({ ...current, password: "" })),
    );
  };
  const addShare = (event: FormEvent) => {
    event.preventDefault();
    void run(
      "/shares",
      "POST",
      { ...share, password: data?.passwordConfigured ? null : share.password },
      () => setShare((current) => ({ ...current, password: "" })),
    );
  };
  return (
    <div className="storage-settings stack">
      {notice && (
        <NotificationPopup tone={notice.error ? "danger" : "success"}>
          {notice.text}
        </NotificationPopup>
      )}
      <header className="panel-heading">
        <div>
          <h2>{t("Storage")}</h2>
          <p className="muted">
            {t(
              "Connect a NAS and share selected folders with your Windows PC.",
            )}
          </p>
        </div>
        <button
          disabled={busy}
          onClick={() => {
            void refresh().catch((error) =>
              setNotice({ text: error.message, error: true }),
            );
          }}
        >
          <RefreshCw size={16} />
          {t("Refresh")}
        </button>
      </header>
      {!data && <p role="status">{t("Loading…")}</p>}
      {data && !data.available && (
        <section className="panel">
          <h3>{t("Prepare storage on this server")}</h3>
          <p>
            {t(
              data.message ||
                "Storage server setup is being prepared automatically. Refresh shortly, or retry server setup.",
            )}
          </p>
          <button
            className="primary"
            disabled={busy}
            onClick={() => {
              void run("/prepare");
            }}
          >
            {t("Prepare server")}
          </button>
        </section>
      )}
      {data?.available && (
        <>
          {data.prerequisite && (
            <section className="panel">
              <h3>{t("Server prerequisite")}</h3>
              <p>{t(data.prerequisite)}</p>
            </section>
          )}
          <section className="panel">
            <h3>
              <HardDrive size={19} />
              {t("Available storage")}
            </h3>
            <StorageLocations locations={data.locations} />
            {!data.locations.length && (
              <p className="muted">
                {t(
                  "No approved local folders yet. Connect a NAS below to add network storage.",
                )}
              </p>
            )}
          </section>
          <AppStorageSettings />
          <div className="storage-columns">
            <section className="panel">
              <h3>
                <Network size={19} />
                {t("Connect a NAS")}
              </h3>
              <p className="muted">
                {t(
                  "Connect an existing NAS share using SMB3. Saved connections reconnect when the server starts.",
                )}
              </p>
              <form className="stack" onSubmit={addNas}>
                <fieldset disabled={busy} className="storage-form">
                  <label>
                    {t("Name")}
                    <input
                      required
                      maxLength={80}
                      value={nas.label}
                      onChange={(e) =>
                        setNas({ ...nas, label: e.target.value })
                      }
                      placeholder={t("My NAS")}
                    />
                  </label>
                  <label>
                    {t("NAS LAN address")}
                    <input
                      required
                      value={nas.server}
                      onChange={(e) =>
                        setNas({ ...nas, server: e.target.value })
                      }
                      placeholder="192.168.1.60"
                      maxLength={15}
                    />
                  </label>
                  <label>
                    {t("Share name")}
                    <input
                      required
                      maxLength={80}
                      value={nas.share}
                      onChange={(e) =>
                        setNas({ ...nas, share: e.target.value })
                      }
                      placeholder={t("Media")}
                    />
                  </label>
                  <label>
                    {t("NAS username")}
                    <input
                      required
                      maxLength={128}
                      autoComplete="off"
                      value={nas.username}
                      onChange={(e) =>
                        setNas({ ...nas, username: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    {t("NAS password")}
                    <input
                      type="password"
                      required
                      maxLength={256}
                      autoComplete="new-password"
                      value={nas.password}
                      onChange={(e) =>
                        setNas({ ...nas, password: e.target.value })
                      }
                    />
                  </label>
                  <label className="storage-check">
                    <input
                      type="checkbox"
                      checked={!nas.readOnly}
                      aria-describedby="nas-permission-help"
                      onChange={(e) =>
                        setNas({ ...nas, readOnly: !e.target.checked })
                      }
                    />
                    {t("Allow changes on the NAS")}
                  </label>
                  <button className="primary" type="submit">
                    {busy ? t("Working…") : t("Connect NAS")}
                  </button>
                </fieldset>
                <p
                  id="nas-permission-help"
                  className="muted storage-permission-help"
                >
                  {t(
                    nas.readOnly
                      ? "Off: You can only view and download files."
                      : "On: You can also create, change and delete files.",
                  )}
                </p>
              </form>
            </section>
            <section className="panel">
              <h3>
                <FolderOpen size={19} />
                {t("Share with Windows")}
              </h3>
              <p className="muted">
                {t(
                  "Create an authenticated network share on MediaHub's LAN address. Existing files and permissions are preserved.",
                )}
              </p>
              <p className="muted">
                {t(
                  "Changing shares briefly reconnects existing Windows sessions. Save open files first.",
                )}
              </p>
              <form className="stack" onSubmit={addShare}>
                <fieldset disabled={busy} className="storage-form">
                  <label>
                    {t("Storage folder")}
                    <select
                      required
                      value={share.storageId}
                      onChange={(e) =>
                        setShare({ ...share, storageId: e.target.value })
                      }
                    >
                      <option value="">{t("Choose storage")}</option>
                      {data.locations.map((row) => (
                        <option
                          key={row.id}
                          value={row.id}
                          disabled={!row.ready}
                        >
                          {t(row.label)}
                          {!row.ready ? ` · ${t("Disconnected")}` : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {t("Windows share name")}
                    <input
                      required
                      pattern="[A-Za-z][A-Za-z0-9_-]{0,39}"
                      maxLength={40}
                      value={share.name}
                      onChange={(e) =>
                        setShare({ ...share, name: e.target.value })
                      }
                    />
                  </label>
                  <label className="storage-check">
                    <input
                      type="checkbox"
                      checked={share.readOnly}
                      onChange={(e) =>
                        setShare({ ...share, readOnly: e.target.checked })
                      }
                    />
                    {t("Read-only access")}
                  </label>
                  {!data.passwordConfigured && (
                    <label>
                      {t("Windows sharing password")}
                      <input
                        type="password"
                        required
                        minLength={12}
                        maxLength={256}
                        autoComplete="new-password"
                        value={share.password}
                        onChange={(e) =>
                          setShare({ ...share, password: e.target.value })
                        }
                      />
                    </label>
                  )}
                  <p className="muted">
                    {t("Windows username:")} <strong>mediahub</strong>
                  </p>
                  <button className="primary" type="submit">
                    {busy ? t("Working…") : t("Create Windows share")}
                  </button>
                </fieldset>
              </form>
            </section>
          </div>
          {!!data.nas.length && (
            <section className="panel">
              <h3>{t("Saved NAS connections")}</h3>
              <div className="storage-locations">
                {data.nas.map((row) => (
                  <article className="storage-location" key={row.id}>
                    <strong>{row.label}</strong>
                    <span>{t(row.ready ? "Connected" : "Disconnected")}</span>
                    {row.error && <p className="muted">{t(row.error)}</p>}
                    <code>{`\\\\${row.server}\\${row.share}`}</code>
                    <p className="muted">
                      {row.readOnly
                        ? t("Read-only access")
                        : t("Read and write access")}
                    </p>
                    {row.writeCachePath && (
                      <div className="storage-cache-info">
                        <strong>
                          {t("NAS write cache on the media drive")}
                        </strong>
                        <code>{row.writeCachePath}</code>
                        <p className="muted">
                          {t(
                            "Keep space for active torrent files. Pending uploads are preserved when the server restarts.",
                          )}
                        </p>
                      </div>
                    )}
                    <div className="actions">
                      <button
                        disabled={busy}
                        onClick={() => {
                          void run(`/nas/${row.id}/connect`);
                        }}
                      >
                        {t("Reconnect")}
                      </button>
                      <button
                        disabled={busy}
                        onClick={async () => {
                          if (
                            await confirm(
                              t(
                                "Disconnect this NAS? Files remain on the NAS; applications using it must be stopped first.",
                              ),
                            )
                          )
                            await run(`/nas/${row.id}/disconnect`);
                        }}
                      >
                        {t("Disconnect")}
                      </button>
                      <button
                        disabled={busy}
                        onClick={async () => {
                          if (
                            await confirm(
                              t(
                                "Remove this NAS connection and its saved login? Files on the NAS are preserved.",
                              ),
                              { danger: true },
                            )
                          )
                            await run(`/nas/${row.id}/remove`);
                        }}
                      >
                        {t("Remove")}
                      </button>
                    </div>
                    {!row.ready && (
                      <>
                        {row.enabled && (
                          <p className="muted">
                            {t(
                              "Connection saved. MediaHub retries automatically every 30 seconds and after a restart.",
                            )}
                          </p>
                        )}
                        <details>
                          <summary>{t("Edit NAS login")}</summary>
                          <form
                            className="storage-form"
                            onSubmit={(event) => {
                              event.preventDefault();
                              const form = event.currentTarget;
                              const values = new FormData(form);
                              void run(
                                `/nas/${row.id}/credentials`,
                                "POST",
                                {
                                  username: values.get("username"),
                                  password: values.get("password"),
                                },
                                () => form.reset(),
                              );
                            }}
                          >
                            <label>
                              {t("NAS username")}
                              <input
                                name="username"
                                required
                                maxLength={128}
                                defaultValue={row.username}
                                autoComplete="off"
                                disabled={busy}
                              />
                            </label>
                            <label>
                              {t("NAS password")}
                              <input
                                name="password"
                                type="password"
                                required
                                maxLength={256}
                                autoComplete="new-password"
                                disabled={busy}
                              />
                            </label>
                            <button
                              className="primary"
                              disabled={busy}
                              type="submit"
                            >
                              {t("Save and reconnect")}
                            </button>
                          </form>
                        </details>
                      </>
                    )}
                  </article>
                ))}
              </div>
            </section>
          )}
          {!!data.shares.length && (
            <section className="panel">
              <h3>{t("Windows network drives")}</h3>
              <p className="muted">
                {t(
                  data.smbRunning
                    ? "Windows sharing is running on the LAN. Check access from your PC using the guide below."
                    : "Windows sharing is not running. Check the connected storage and refresh.",
                )}
              </p>
              {data.shares.map((row) => (
                <article className="storage-location" key={row.name}>
                  <div className="panel-heading">
                    <strong>{row.name}</strong>
                    <button
                      disabled={busy}
                      onClick={async () => {
                        if (
                          await confirm(
                            t(
                              "Remove this Windows share? Open Windows connections will close; media files are preserved.",
                            ),
                            { danger: true },
                          )
                        )
                          await run(
                            `/shares/${encodeURIComponent(row.name)}`,
                            "DELETE",
                          );
                      }}
                    >
                      {t("Remove share")}
                    </button>
                  </div>
                  <p>
                    {t(
                      row.readOnly
                        ? "Read-only access"
                        : "Read and write access",
                    )}
                  </p>
                  <WindowsDriveGuide share={row} />
                </article>
              ))}
              <details>
                <summary>{t("Change Windows sharing password")}</summary>
                <p className="muted">
                  {t(
                    "All MediaHub Windows shares use this account. Reconnect your mapped drives with the new password afterwards.",
                  )}
                </p>
                <form
                  className="storage-password"
                  onSubmit={async (e) => {
                    e.preventDefault();
                    if (
                      await confirm(
                        t(
                          "Change the password for all MediaHub Windows shares?",
                        ),
                      )
                    )
                      await run("/password", "POST", { password }, () =>
                        setPassword(""),
                      );
                  }}
                >
                  <label>
                    {t("New password")}
                    <input
                      disabled={busy}
                      required
                      type="password"
                      minLength={12}
                      maxLength={256}
                      autoComplete="new-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                    />
                  </label>
                  <button disabled={busy}>{t("Save password")}</button>
                </form>
              </details>
            </section>
          )}
          <p className="muted">
            {t(
              "NAS storage can be attached to apps here or in each app's settings. Existing files are kept.",
            )}
          </p>
        </>
      )}
    </div>
  );
}
