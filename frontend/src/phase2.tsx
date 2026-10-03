import { getLocale, translateText, t } from "./i18n";
import { ServiceIcon } from "./service-icon";

import { LayoutGroup } from "./page-layout";
import { AppUninstall } from "./app-uninstall";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
  type DragEvent,
} from "react";
import {
  ArrowLeft,
  Box,
  FileText,
  Folder,
  FolderPlus,
  HardDrive,
  RefreshCw,
  Server,
  Upload,
  X,
} from "lucide-react";
import { api, uploadMediaFile } from "./api";
import { droppedMediaFiles, type MediaUploadFile } from "./media-drop";
import { Link } from "react-router-dom";
import { bytes, fileFormat } from "./format";
import type { HostInfo, LogicalStorage } from "./hosts";
import type { Storage, AppInfo } from "./contracts";
import type {
  AgentStatus,
  CatalogApp,
  DirectoryListing,
  Discovery,
  ImportPlan,
  MediaFileListing,
  NetworkConfig,
  PlannedStorage,
} from "./phase2-types";

export function useLoad<T>(path: string) {
  const [result, setResult] = useState<{
    path: string;
    data?: T;
    error: string;
  }>({ path, error: "" });
  const activeRequest = useRef<AbortController | null>(null);
  const reload = useCallback(() => {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    api<T>(path, "GET", undefined, controller.signal)
      .then((d) => {
        if (!controller.signal.aborted) setResult({ path, data: d, error: "" });
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setResult((current) => ({
            path,
            data: current.path === path ? current.data : undefined,
            error: e.message,
          }));
      });
  }, [path]);
  useEffect(() => {
    reload();
    return () => activeRequest.current?.abort();
  }, [reload]);
  return {
    data: result.path === path ? result.data : undefined,
    error: result.path === path ? result.error : "",
    reload,
  };
}
export function Panel({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>{t(title)}</h2>
      </div>
      <div className="phase-content">{children}</div>
    </section>
  );
}
export function ErrorBox({ error }: { error: string }) {
  return error ? (
    <div className="notice" role="alert">
      {t(error)}
    </div>
  ) : null;
}

export function RuntimePanel() {
  const { data, error, reload } = useLoad<AgentStatus>("/runtime");
  return (
    <Panel title={t("Agent & app runtime")}>
      <ErrorBox error={error} />
      {data ? (
        <>
          <div className="runtime-grid">
            <div>
              <Server />
              <strong>
                {data.connected ? t("Agent connected") : t("Agent unavailable")}
              </strong>
              <span>{data.version || translateText(data.message)}</span>
            </div>
            <div>
              <Box />
              <strong>
                {data.docker.available
                  ? t("Docker available")
                  : t("Docker not detected")}
              </strong>
              <span>
                {data.docker.version ||
                  t("Core works without Docker. Real apps require it.")}
              </span>
            </div>
          </div>
          {data.fixtureMode && (
            <div className="notice">
              {t(
                "Development discovery fixtures enabled — these are not your real services.",
              )}
            </div>
          )}
        </>
      ) : (
        <p>{t("Checking runtime…")}</p>
      )}
      <button onClick={reload}>{t("Refresh runtime")}</button>
    </Panel>
  );
}

export function StorageSummary() {
  const { data, error } = useLoad<Storage[]>("/storage/locations");
  const groups = new Map<
    string,
    {
      names: string[];
      totalBytes: number | null;
      freeBytes: number | null;
      writable: boolean;
      filesystem: string | null | undefined;
    }
  >();
  for (const item of data || []) {
    if (!mediaKinds.has(item.kind) || !item.readable) continue;
    const key = [
      item.filesystem || "unknown",
      item.totalBytes ?? "unknown",
      item.freeBytes ?? "unknown",
      item.writable ? "rw" : "ro",
    ].join(":");
    const current = groups.get(key);
    if (current) current.names.push(item.name);
    else
      groups.set(key, {
        names: [item.name],
        totalBytes: item.totalBytes,
        freeBytes: item.freeBytes,
        writable: item.writable,
        filesystem: item.filesystem,
      });
  }
  const volumes = [...groups.entries()].sort(([, left], [, right]) => {
    if (left.writable !== right.writable) return left.writable ? -1 : 1;
    return left.names.join(" ").localeCompare(right.names.join(" "));
  });
  const primary = volumes.filter(([, group]) => group.writable);
  const secondary = volumes.filter(([, group]) => !group.writable);
  const renderVolume = ([key, group]: (typeof volumes)[number]) => {
    const used =
      group.totalBytes != null && group.freeBytes != null
        ? group.totalBytes - group.freeBytes
        : null;
    const percent =
      used != null && group.totalBytes
        ? Math.round((used / group.totalBytes) * 100)
        : 0;
    const legacy = group.names.some((name) =>
      name.toLowerCase().includes("legacy"),
    );
    return (
      <div className="storage-volume" key={key}>
        <div className="storage-volume-head">
          <HardDrive size={20} />
          <span>
            <strong>
              {legacy ? t("Legacy media archive") : t("MediaHub storage")}
            </strong>
            <small>
              {group.writable
                ? t("Main read/write media drive")
                : t("Additional read-only archive")}
            </small>
          </span>
        </div>
        <div className="storage-volume-number">
          {group.writable
            ? t("{value0} free", { value0: bytes(group.freeBytes) })
            : t("{value0} stored", { value0: bytes(used) })}
          <small>
            {t("of ")}
            {bytes(group.totalBytes)}
          </small>
        </div>
        <div className="meter" role="presentation">
          <span style={{ width: `${percent}%` }} />
        </div>
      </div>
    );
  };
  return (
    <Panel title={t("Media storage")}>
      <ErrorBox error={error} />
      {data && groups.size === 0 && (
        <p className="muted">
          {t("No readable media storage configured yet.")}
        </p>
      )}
      <div className="storage-volume-grid">{primary.map(renderVolume)}</div>
      {secondary.length > 0 && (
        <details className="storage-secondary">
          <summary>
            {t(
              secondary.length === 1
                ? "{count} additional mounted archive"
                : "{count} additional mounted archives",
              { count: secondary.length },
            )}
          </summary>
          <div className="storage-volume-grid">
            {secondary.map(renderVolume)}
          </div>
        </details>
      )}
      <p className="muted">
        {t(
          "Folder mappings are hidden here. Open technical mode only when troubleshooting mounts.",
        )}
      </p>
    </Panel>
  );
}

export function FolderBrowser({
  onSelect,
  onClose,
}: {
  onSelect: (path: string, action: "existing" | "create") => void;
  onClose: () => void;
}) {
  const [path, setPath] = useState<string | null>(null);
  const [folderName, setFolderName] = useState("");
  const { data, error } = useLoad<DirectoryListing>(
    "/agent/directories" + (path ? "?path=" + encodeURIComponent(path) : ""),
  );
  const separator = path?.includes("\\") ? "\\" : "/";
  const proposed = path
    ? path.replace(/[\\/]$/, "") + separator + folderName
    : "";
  return (
    <div className="modal-backdrop">
      <section
        className="folder-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t("Browse server folders")}
      >
        <header>
          <div>
            <h2>{t("Server folders")}</h2>
            <p>{t("Agent filesystem · directories only")}</p>
          </div>
          <button aria-label={t("Close folder browser")} onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <ErrorBox error={error} />
        <code>{path || t("Approved storage roots")}</code>
        {path && (
          <button onClick={() => setPath(data?.parent || null)}>
            {t("Parent folder")}
          </button>
        )}
        <div className="folder-list">
          {data?.folders.map((folder) => (
            <button key={folder.path} onClick={() => setPath(folder.path)}>
              <Folder size={18} />
              {folder.name}
            </button>
          ))}
          {data && data.folders.length === 0 && (
            <p className="muted">{t("No subfolders.")}</p>
          )}
        </div>
        {data?.capacity && (
          <div className="folder-capacity">
            {bytes(data.capacity.freeBytes)}
            {t(" free /")} {bytes(data.capacity.totalBytes)}
            {t(" · Read:")} {data.capacity.readable ? t("yes") : t("no")}
            {t(" · Write:")} {data.capacity.writable ? t("reported") : t("no")}
          </div>
        )}
        {path && (
          <>
            <button
              className="primary"
              onClick={() => onSelect(path, "existing")}
            >
              {t("Use this folder")}
            </button>
            <label>
              {t("New folder name")}
              <input
                value={folderName}
                onChange={(e) => setFolderName(e.target.value)}
                placeholder={t("movies")}
              />
            </label>
            <code>{proposed}</code>
            <button
              disabled={
                !folderName ||
                /[\\/]/.test(folderName) ||
                folderName === "." ||
                folderName === ".."
              }
              onClick={() => onSelect(proposed, "create")}
            >
              <FolderPlus size={16} />
              {t("Select new folder")}
            </button>
            <small>
              {t("Nothing is created until you explicitly confirm and apply.")}
            </small>
          </>
        )}
      </section>
    </div>
  );
}

const storageTypes = [
  ["appdata", "App Data"],
  ["downloads", "Downloads"],
  ["incomplete_downloads", "Incomplete Downloads"],
  ["completed_downloads", "Completed Downloads"],
  ["movies", "Movies"],
  ["tv", "TV Shows"],
  ["backups", "Backups"],
  ["temp", "Temporary"],
  ["custom", "Custom"],
];
export function StorageEditor({
  onAdd,
}: {
  onAdd: (item: PlannedStorage) => Promise<void> | void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("movies");
  const [path, setPath] = useState("");
  const [action, setAction] = useState<"existing" | "create">("existing");
  const [confirmed, setConfirmed] = useState(false);
  const [browse, setBrowse] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await onAdd({
        name,
        kind,
        path,
        action,
        confirmed_path: action === "create" && confirmed ? path : null,
      });
      setName("");
      setPath("");
      setConfirmed(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <form className="storage-form" onSubmit={submit}>
        <ErrorBox error={error} />
        <label>
          {t("Name")}
          <input
            name="storage_name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={80}
          />
        </label>
        <label>
          {t("Storage type")}
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {storageTypes.map(([value, label]) => (
              <option key={value} value={value}>
                {translateText(label)}
              </option>
            ))}
          </select>
        </label>
        <label className="wide">
          {t("Host path")}
          <input
            name="storage_path"
            value={path}
            onChange={(e) => {
              setPath(e.target.value);
              setConfirmed(false);
            }}
            required
          />
        </label>
        <div className="button-row wide">
          <button type="button" onClick={() => setBrowse(true)}>
            <Folder size={17} />
            {t("Browse server")}
          </button>
          <select
            aria-label={t("Folder action")}
            value={action}
            onChange={(e) => {
              setAction(e.target.value as "existing" | "create");
              setConfirmed(false);
            }}
          >
            <option value="existing">{t("Use Existing Folder")}</option>
            <option value="create">{t("Create New Folder")}</option>
          </select>
        </div>
        {action === "create" && (
          <label className="check-label wide">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            {t("I confirm creation of exactly:")}{" "}
            <code>{path || t("Choose a path first")}</code>
          </label>
        )}
        <p className="muted wide">
          {t(
            "Only approved agent roots are accessible. Existing files are never moved.",
          )}
        </p>
        <button
          className="primary"
          disabled={busy || (action === "create" && !confirmed)}
        >
          {busy ? t("Validating…") : t("Add storage location")}
        </button>
      </form>
      {browse && (
        <FolderBrowser
          onClose={() => setBrowse(false)}
          onSelect={(p, a) => {
            setPath(p);
            setAction(a);
            setConfirmed(false);
            setBrowse(false);
          }}
        />
      )}
    </>
  );
}

export function StorageWorkspace() {
  const { data, error, reload } = useLoad<Storage[]>("/storage/locations");
  const [editing, setEditing] = useState<Storage | null>(null);
  const [message, setMessage] = useState("");
  const add = async (item: PlannedStorage) => {
    if (item.action === "create")
      await api("/agent/directories/create", "POST", {
        path: item.path,
        confirmed_path: item.confirmed_path,
      });
    await api("/storage/locations", "POST", {
      name: item.name,
      kind: item.kind,
      path: item.path,
    });
    reload();
    setMessage("Location saved. No existing files were moved.");
  };
  return (
    <LayoutGroup id="phase2-StorageWorkspace-1" className="stack">
      <Panel title={t("Storage locations")}>
        <ErrorBox error={error} />
        {message && <p className="success">{translateText(message)}</p>}
        {data?.length ? (
          data.map((item) => (
            <div className="storage-row" key={item.id}>
              <HardDrive />
              <div>
                <strong>{item.name}</strong>
                <code>{item.path}</code>
                <small>
                  {translateText(item.kind)}
                  {t(" · Read ")}
                  {t(String(item.readable))}
                  {t(" / Write")} {t(String(item.writable))}
                </small>
                {item.error && <small>{translateText(item.error)}</small>}
                <small>
                  {t("Owner: ")}
                  {item.owner ?? t("Unavailable")}
                  {t(" · UID/GID:")} {item.uid ?? t("n/a")}/
                  {item.gid ?? t("n/a")}
                </small>
                <small>
                  {t("Permissions: ")}
                  {item.permissions ?? t("Unavailable")} ·{" "}
                  {item.filesystem ?? t("Unknown filesystem")} ·{" "}
                  {bytes(item.totalBytes)}
                  {t(" total")}
                </small>
              </div>
              <span>
                {bytes(item.freeBytes)}
                {t(" free")}
              </span>
              <button onClick={() => setEditing(item)}>
                {t("Change mapping")}
              </button>
            </div>
          ))
        ) : (
          <div className="empty">
            <h3>{t("No locations registered")}</h3>
            <p>
              {t(
                "Choose existing storage or explicitly create a new directory.",
              )}
            </p>
          </div>
        )}
      </Panel>
      <Panel title={t("Add storage")}>
        <StorageEditor onAdd={add} />
      </Panel>
      {editing && (
        <FolderBrowser
          onClose={() => setEditing(null)}
          onSelect={async (path, action) => {
            if (action === "create") {
              setMessage(
                "Create and register new folders using Add storage; mapping changes only select existing folders.",
              );
              return;
            }
            try {
              await api("/storage/locations/" + editing.id, "PUT", {
                name: editing.name,
                kind: editing.kind,
                path,
              });
              setEditing(null);
              reload();
              setMessage("Mapping changed. Existing files were NOT moved.");
            } catch (e) {
              setMessage((e as Error).message);
            }
          }}
        />
      )}
    </LayoutGroup>
  );
}

const mediaKinds = new Set([
  "downloads",
  "incomplete_downloads",
  "completed_downloads",
  "movies",
  "tv",
  "other",
  "custom",
]);

export function MediaFiles() {
  const locations = useLoad<Storage[]>("/storage/locations");
  const [locationId, setLocationId] = useState("");
  const [listing, setListing] = useState<MediaFileListing>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploads, setUploads] = useState<
    {
      id: string;
      name: string;
      progress: number;
      state:
        "queued" | "uploading" | "stopping" | "stopped" | "complete" | "error";
      message?: string;
    }[]
  >([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const dropReader = useRef<AbortController | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [readingDrop, setReadingDrop] = useState(false);
  const folderInput = useRef<HTMLInputElement>(null);
  const uploadPicker = useRef<HTMLDivElement>(null);
  const uploadButton = useRef<HTMLButtonElement>(null);
  const [uploadChoicesOpen, setUploadChoicesOpen] = useState(false);
  useEffect(() => {
    if (!uploadChoicesOpen) return;
    const outside = (event: PointerEvent) => {
      if (!uploadPicker.current?.contains(event.target as Node))
        setUploadChoicesOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setUploadChoicesOpen(false);
        uploadButton.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [uploadChoicesOpen]);
  const uploadControllers = useRef(new Map<string, AbortController>());
  const [uploading, setUploading] = useState(false);
  useEffect(() => {
    const controllers = uploadControllers.current;
    const warn = (event: BeforeUnloadEvent) => {
      if (controllers.size || dropReader.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    const preventFileNavigation = (event: globalThis.DragEvent) => {
      if (event.dataTransfer?.types.includes("Files")) event.preventDefault();
    };
    window.addEventListener("dragover", preventFileNavigation);
    window.addEventListener("drop", preventFileNavigation);
    return () => {
      window.removeEventListener("beforeunload", warn);
      window.removeEventListener("dragover", preventFileNavigation);
      window.removeEventListener("drop", preventFileNavigation);
      dropReader.current?.abort();
      controllers.forEach((controller) => controller.abort());
    };
  }, []);
  const stopUpload = (id?: string) => {
    if (!id) dropReader.current?.abort();
    uploadControllers.current.forEach((controller, key) => {
      if (!id || key === id) controller.abort();
    });
    setUploads((current) =>
      current.map((item) =>
        (!id || item.id === id) && ["uploading", "queued"].includes(item.state)
          ? { ...item, state: item.state === "queued" ? "stopped" : "stopping" }
          : item,
      ),
    );
  };

  const available = (locations.data || []).filter((item) =>
    mediaKinds.has(item.kind),
  );

  const open = useCallback(async (identifier: string, path?: string) => {
    setLoading(true);
    setError("");
    try {
      const query = path ? "?path=" + encodeURIComponent(path) : "";
      setListing(
        await api<MediaFileListing>(
          `/storage/locations/${identifier}/files${query}`,
        ),
      );
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!locationId && available.length) setLocationId(available[0].id);
  }, [available, locationId]);

  useEffect(() => {
    if (locationId) open(locationId);
  }, [locationId, open]);

  const relative = listing
    ? listing.path.slice(listing.location.path.length).replace(/^\/+/, "") ||
      "Top folder"
    : "Top folder";
  const selectedLocation = available.find((item) => item.id === locationId);

  const uploadFiles = useCallback(
    async (selected: MediaUploadFile[]) => {
      if (!selected.length || !listing || uploadControllers.current.size)
        return;
      if (selected.length > 10000) {
        setError("Choose a folder with at most 10,000 files per upload.");
        return;
      }
      setUploading(true);
      setError("");
      const queue = selected.map(({ file, relativePath }) => ({
        id: crypto.randomUUID(),
        file,
        controller: new AbortController(),
        name: relativePath,
      }));
      queue.forEach((item) =>
        uploadControllers.current.set(item.id, item.controller),
      );
      setUploads(
        queue.map((item) => ({
          id: item.id,
          name: item.name,
          progress: 0,
          state: "queued",
        })),
      );
      const directories = new Map<string, string>();
      const failedDirectories = new Map<string, Error>();
      let folderError = "";
      try {
        for (const { id, file, controller, name } of queue) {
          const signal = controller.signal;
          try {
            signal.throwIfAborted();
            setUploads((current) =>
              current.map((item) =>
                item.id === id ? { ...item, state: "uploading" } : item,
              ),
            );
            let destination = listing.path;
            if (name !== file.name) {
              const parts = name.split("/");
              if (
                parts.length < 2 ||
                parts.pop() !== file.name ||
                parts.some(
                  (p) => !p || p === "." || p === ".." || p.includes("\\"),
                )
              ) {
                throw new Error(
                  "The browser did not provide a valid folder path",
                );
              }
              const relativePath = parts.join("/");
              if (failedDirectories.has(relativePath))
                throw failedDirectories.get(relativePath)!;
              if (!directories.has(relativePath)) {
                try {
                  const created = await api<{ path: string }>(
                    `/storage/locations/${locationId}/files/folder`,
                    "POST",
                    {
                      path: listing.path,
                      relativePath,
                    },
                    signal,
                  );
                  directories.set(relativePath, created.path);
                } catch (caught) {
                  if (!signal.aborted) {
                    failedDirectories.set(relativePath, caught as Error);
                    folderError = `Cannot prepare upload folder: ${(caught as Error).message}`;
                  }
                  throw caught;
                }
              }
              destination = directories.get(relativePath)!;
            }
            signal.throwIfAborted();
            await uploadMediaFile(
              locationId,
              destination,
              file,
              (progress) => {
                if (!signal.aborted)
                  setUploads((current) =>
                    current.map((item) =>
                      item.id === id ? { ...item, progress } : item,
                    ),
                  );
              },
              signal,
            );
            setUploads((current) =>
              current.map((item) =>
                item.id === id
                  ? { ...item, progress: 100, state: "complete" }
                  : item,
              ),
            );
          } catch (caught) {
            setUploads((current) =>
              current.map((item) =>
                item.id === id
                  ? {
                      ...item,
                      state: signal.aborted ? "stopped" : "error",
                      message: (caught as Error).message,
                    }
                  : item,
              ),
            );
          } finally {
            uploadControllers.current.delete(id);
          }
        }
      } finally {
        setUploading(false);
        await open(locationId, listing.path);
        if (folderError) setError(folderError);
        if (fileInput.current) fileInput.current.value = "";
        if (folderInput.current) folderInput.current.value = "";
      }
    },
    [listing, locationId, open],
  );

  const canUpload =
    !!listing && !!selectedLocation?.writable && !loading && !uploading;
  const drop = async (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    setDragActive(false);
    if (!canUpload || dropReader.current || uploadControllers.current.size)
      return;
    const controller = new AbortController();
    dropReader.current = controller;
    setUploading(true);
    setReadingDrop(true);
    setUploadChoicesOpen(false);
    setError("");
    try {
      const selected = await droppedMediaFiles(
        event.dataTransfer,
        controller.signal,
      );
      controller.signal.throwIfAborted();
      setReadingDrop(false);
      if (!selected.length)
        setError("No files found. Empty folders are not uploaded.");
      else await uploadFiles(selected);
    } catch (caught) {
      if (!controller.signal.aborted) setError((caught as Error).message);
    } finally {
      dropReader.current = null;
      setReadingDrop(false);
      setUploading(false);
    }
  };

  return (
    <div
      className={`media-drop-area${dragActive ? " drag-active" : ""}`}
      onDragOver={(event) => {
        if (!event.dataTransfer.types.includes("Files")) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = canUpload ? "copy" : "none";
        setDragActive(canUpload);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null))
          setDragActive(false);
      }}
      onDrop={drop}
    >
      <Panel title={t("Media files")}>
        <p className="muted">
          {t(
            "Browse the folders Plex and Seedbox use, and securely upload files or folders from this device. Existing files cannot be overwritten, moved or deleted here.",
          )}
        </p>
        <p className="media-drop-hint" role="status">
          {readingDrop
            ? t("Reading files and folders…")
            : dragActive
              ? t("Drop here to upload to the current folder")
              : t(
                  "Drag files or folders anywhere into this panel to upload to the current folder.",
                )}
        </p>
        <ErrorBox error={locations.error || error} />
        {!locations.data ? (
          !locations.error && <p>{t("Loading media locations…")}</p>
        ) : available.length === 0 ? (
          <div className="empty">
            <Folder size={28} />
            <h3>{t("No media folders registered")}</h3>
            <p>{t("Add a Movies, TV or Downloads storage location first.")}</p>
          </div>
        ) : (
          <>
            <div className="media-browser-toolbar">
              <label>
                {t("Media location")}
                <select
                  value={locationId}
                  disabled={uploading}
                  onChange={(event) => setLocationId(event.target.value)}
                >
                  {available.map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="media-browser-actions">
                <button
                  disabled={!listing?.parent || loading || uploading}
                  onClick={() =>
                    listing?.parent && open(locationId, listing.parent)
                  }
                >
                  <ArrowLeft size={16} />
                  {t(" Parent folder")}
                </button>
                <button
                  aria-label={t("Refresh media files")}
                  disabled={loading}
                  onClick={() => open(locationId, listing?.path)}
                >
                  <RefreshCw className={loading ? "spin" : ""} size={16} />
                  {t("Refresh")}
                </button>
                <input
                  aria-label={t("Choose files to upload")}
                  className="visually-hidden"
                  multiple
                  onChange={(event) =>
                    uploadFiles(
                      Array.from(event.target.files || [], (file) => ({
                        file,
                        relativePath: file.name,
                      })),
                    )
                  }
                  ref={fileInput}
                  type="file"
                />
                <input
                  aria-label={t("Choose folder to upload")}
                  className="visually-hidden"
                  type="file"
                  multiple
                  {...{ webkitdirectory: "" }}
                  ref={folderInput}
                  onChange={(event) =>
                    uploadFiles(
                      Array.from(event.target.files || [], (file) => ({
                        file,
                        relativePath: file.webkitRelativePath,
                      })),
                    )
                  }
                />
                <div
                  className="media-upload-picker"
                  ref={uploadPicker}
                  onBlur={(event) => {
                    if (!event.currentTarget.contains(event.relatedTarget))
                      setUploadChoicesOpen(false);
                  }}
                >
                  <button
                    className="primary"
                    ref={uploadButton}
                    aria-expanded={uploadChoicesOpen}
                    aria-controls="media-upload-choices"
                    disabled={
                      !listing ||
                      !selectedLocation?.writable ||
                      loading ||
                      uploading
                    }
                    onClick={() => setUploadChoicesOpen((open) => !open)}
                  >
                    <Upload size={16} />
                    {t(" Upload")}
                  </button>
                  {uploadChoicesOpen && (
                    <div
                      className="media-upload-choices"
                      id="media-upload-choices"
                      role="group"
                      aria-label={t("Upload options")}
                    >
                      <button
                        onClick={() => {
                          setUploadChoicesOpen(false);
                          uploadButton.current?.focus();
                          fileInput.current?.click();
                        }}
                      >
                        <FileText size={16} />
                        {t(" Files")}
                      </button>
                      <button
                        onClick={() => {
                          setUploadChoicesOpen(false);
                          uploadButton.current?.focus();
                          folderInput.current?.click();
                        }}
                      >
                        <Folder size={16} />
                        {t(" Folder")}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
            {uploads.length > 0 && (
              <div className="media-upload-list" aria-live="polite">
                <div className="media-upload-summary">
                  <span>
                    {uploads.filter((item) => item.state === "complete").length}{" "}
                    {t("of ")}
                    {uploads.length}
                    {t(" files uploaded")}
                  </span>
                  {uploading && (
                    <button onClick={() => stopUpload()}>
                      {t("Stop all")}
                    </button>
                  )}
                </div>
                <p className="muted">
                  {t(
                    "Folders keep their structure. Empty folders are not included. Keep this page open; stopping keeps completed files.",
                  )}
                </p>
                {uploads.map((item) => (
                  <div
                    className={`media-upload-item ${item.state}`}
                    key={item.id}
                  >
                    <div>
                      <strong>{item.name}</strong>
                      <small>
                        {item.state === "complete"
                          ? t("Upload complete")
                          : item.state === "error"
                            ? translateText(item.message)
                            : item.state === "queued"
                              ? t("Waiting")
                              : item.state === "stopped"
                                ? t("Stopped")
                                : item.state === "stopping"
                                  ? t("Stopping and cleaning up...")
                                  : t("{value0}% uploaded", {
                                      value0: item.progress,
                                    })}
                      </small>
                    </div>
                    <div className="media-upload-progress">
                      <span style={{ width: `${item.progress}%` }} />
                    </div>
                    {["queued", "uploading", "stopping"].includes(
                      item.state,
                    ) && (
                      <button
                        aria-label={t("Stop upload {value0}", {
                          value0: item.name,
                        })}
                        disabled={item.state === "stopping"}
                        onClick={() => stopUpload(item.id)}
                      >
                        {item.state === "stopping"
                          ? t("Stopping...")
                          : t("Stop")}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
            <div className="media-path">
              <Folder size={16} />
              <span>{relative}</span>
            </div>
            <div className="media-file-list" aria-busy={loading}>
              {listing?.items.map((item) => (
                <button
                  className="media-file-row"
                  title={item.name}
                  disabled={item.type === "file" || uploading}
                  key={item.path}
                  onClick={() =>
                    item.type === "folder" && open(locationId, item.path)
                  }
                >
                  {item.type === "folder" ? (
                    <Folder size={19} />
                  ) : (
                    <FileText size={19} />
                  )}
                  <span>
                    <strong>{item.name}</strong>
                    <small>
                      {item.type === "folder"
                        ? t("{value0}{value1} · Folder", {
                            value0: item.sizeComplete ? "" : "At least ",
                            value1: bytes(item.sizeBytes),
                          })
                        : t("{value0} · {value1} · {value2}", {
                            value0: fileFormat(item.name),
                            value1: bytes(item.sizeBytes),
                            value2: new Date(
                              item.modifiedAt * 1000,
                            ).toLocaleDateString(getLocale()),
                          })}
                    </small>
                  </span>
                </button>
              ))}
              {!loading && listing?.items.length === 0 && (
                <p className="muted">{t("This folder is empty.")}</p>
              )}
              {loading && <p className="muted">{t("Reading folder…")}</p>}
            </div>
            {listing?.truncated && (
              <p className="muted">
                {t(
                  "Showing the first 500 entries. Open a subfolder to narrow the list.",
                )}
              </p>
            )}
          </>
        )}
      </Panel>
    </div>
  );
}

export function NetworkForm({
  value,
  onChange,
}: {
  value: NetworkConfig;
  onChange: (n: NetworkConfig) => void;
}) {
  const [originsText, setOriginsText] = useState(
    value.allowed_origins.join(", "),
  );
  const [proxiesText, setProxiesText] = useState(
    value.trusted_proxies.join(", "),
  );
  const update = (key: keyof NetworkConfig, next: string | number | string[]) =>
    onChange({ ...value, [key]: next });
  return (
    <div className="network-form">
      <label>
        {t("Listen host")}
        <input
          value={value.listen_host}
          onChange={(e) => update("listen_host", e.target.value)}
        />
      </label>
      <label>
        {t("HTTP port")}
        <input
          type="number"
          min={1024}
          max={65535}
          value={value.port}
          onChange={(e) => update("port", Number(e.target.value))}
        />
      </label>
      <label className="wide">
        {t("Base URL")}
        <input
          value={value.base_url}
          onChange={(e) => update("base_url", e.target.value)}
        />
      </label>
      <label className="wide">
        {t("Allowed origins (comma-separated)")}
        <input
          value={originsText}
          onChange={(e) => {
            setOriginsText(e.target.value);
            update(
              "allowed_origins",
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            );
          }}
        />
      </label>
      <label className="wide">
        {t("Trusted proxy IPs / CIDRs (optional)")}
        <input
          value={proxiesText}
          onChange={(e) => {
            setProxiesText(e.target.value);
            update(
              "trusted_proxies",
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            );
          }}
        />
      </label>
      {!["127.0.0.1", "::1"].includes(value.listen_host) && (
        <div className="notice wide">
          {t(
            "This exposes Core beyond localhost. Authentication does not encrypt HTTP. No firewall, router or reverse proxy will be configured automatically.",
          )}
        </div>
      )}
      <p className="muted wide">
        {t(
          "Saved as pending. Network activation requires an explicit restart with --saved-network.",
        )}
      </p>
    </div>
  );
}

export function ConfigurationForm({ app }: { app: CatalogApp }) {
  const loaded = useLoad<{
    values: Record<string, string>;
    secrets: Record<string, { configured: boolean }>;
  }>("/catalog/" + app.id + "/configuration");
  const [values, setValues] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api("/catalog/" + app.id + "/configuration", "PUT", { values });
      setValues({});
      loaded.reload();
      setMessage(
        "Configuration saved. Secrets are encrypted and never returned.",
      );
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <form className="dynamic-form" onSubmit={submit}>
      <ErrorBox error={error || loaded.error} />
      {app.configFields.map((field) => (
        <label key={field.name}>
          {translateText(field.label)}
          {field.type === "select" ? (
            <select
              value={
                values[field.name] ??
                loaded.data?.values[field.name] ??
                field.default ??
                ""
              }
              onChange={(e) =>
                setValues({ ...values, [field.name]: e.target.value })
              }
            >
              {field.options.map((option) => (
                <option key={option}>{option}</option>
              ))}
            </select>
          ) : (
            <input
              type={field.secret ? "password" : "text"}
              autoComplete={field.secret ? "new-password" : "off"}
              value={
                values[field.name] ??
                (field.secret
                  ? ""
                  : (loaded.data?.values[field.name] ?? field.default ?? ""))
              }
              placeholder={
                field.secret
                  ? loaded.data?.secrets[field.name]?.configured
                    ? t("Configured — leave blank to keep")
                    : t("Not configured")
                  : field.placeholder || undefined
              }
              onChange={(e) =>
                setValues({ ...values, [field.name]: e.target.value })
              }
            />
          )}{" "}
          {field.secret && (
            <small>
              {loaded.data?.secrets[field.name]?.configured
                ? t("Configured: yes")
                : t("Configured: no")}
            </small>
          )}
          {field.description && (
            <small>{translateText(field.description)}</small>
          )}
          {field.helpUrl && (
            <a href={field.helpUrl} target="_blank" rel="noreferrer">
              {t("Open official guidance →")}
            </a>
          )}
        </label>
      ))}
      <button>{t("Save app configuration")}</button>
      {message && (
        <p role="status" className="success">
          {translateText(message)}
        </p>
      )}
    </form>
  );
}

export function CatalogPage({
  selected,
  onSelect,
  showInstalled = false,
}: {
  selected?: string[];
  onSelect?: (ids: string[]) => void;
  showInstalled?: boolean;
}) {
  const { data, error } = useLoad<CatalogApp[]>("/catalog");
  const installed = useLoad<AppInfo[]>("/apps");
  const integrations =
    useLoad<{ id: string; enabled: boolean }[]>("/integrations");
  const hosts = useLoad<HostInfo[]>("/hosts");
  const logical = useLoad<LogicalStorage[]>("/storage/logical");
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState("");
  const [plan, setPlan] = useState<Record<string, unknown>>();
  const [planError, setError] = useState("");
  const [mappings, setMappings] = useState<
    Record<string, Record<string, string>>
  >({});
  const ready = !!data && !!installed.data && !!integrations.data;
  const fjordHubConnected = !!integrations.data?.some((item) => item.enabled);
  const visibleApps = data
    ?.filter((app) => app.availability !== "development")
    .filter((app) => {
      if (showInstalled) return true;
      if (app.id === "org.mediahub.fjordhub" && fjordHubConnected) return false;
      return !installed.data?.some((item) => item.packageId === app.id);
    });
  return (
    <div className="stack">
      <ErrorBox
        error={error || installed.error || integrations.error || planError}
      />
      {!ready ? (
        <div
          className="apps-grid app-skeleton-grid"
          aria-busy="true"
          aria-label={t("Loading App Store")}
        >
          {[0, 1, 2, 3].map((item) => (
            <div className="panel app-skeleton" key={item}>
              <span />
              <span />
              <span />
            </div>
          ))}
        </div>
      ) : (
        <LayoutGroup id="phase2-CatalogPage-1" className="apps-grid store-grid">
          {visibleApps?.map((app) => {
            const installedApp = installed.data?.find(
              (item) => item.packageId === app.id,
            );
            const connected =
              app.id === "org.mediahub.fjordhub" && fjordHubConnected;
            return (
              <section className="panel app-detail store-card" key={app.id}>
                <div className="panel-heading">
                  <div className="app-icon">
                    <ServiceIcon packageId={app.id} />
                  </div>
                  <span className="badge">
                    {installedApp
                      ? t("Installed")
                      : connected
                        ? t("Connected")
                        : app.availability === "available"
                          ? t("Guided setup")
                          : t("Coming soon")}
                  </span>
                </div>
                <h2>{translateText(app.name)}</h2>
                <p>{translateText(app.description)}</p>
                <p className="muted">
                  {translateText(app.category)}
                  {t(" · v")}
                  {app.version} · {translateText(app.maintainer.name)}
                </p>
                <div className="store-card-action">
                  {installedApp?.detailPath ? (
                    <Link className="primary" to={installedApp.detailPath}>
                      {t("Open ")}
                      {translateText(app.name)} →
                    </Link>
                  ) : connected ? (
                    <Link className="primary" to="/integrations">
                      {t("Manage FjordHub →")}
                    </Link>
                  ) : app.id === "org.mediahub.plex" ? (
                    <Link className="primary" to="/apps/install/plex">
                      {t("Install Plex →")}
                    </Link>
                  ) : app.id === "org.mediahub.seedbox" ? (
                    <Link className="primary" to="/apps/install/seedbox">
                      {t("Install Seedbox →")}
                    </Link>
                  ) : app.id === "org.mediahub.cloudflared" ? (
                    <Link className="primary" to="/store/cloudflare">
                      {t("Set up Cloudflare →")}
                    </Link>
                  ) : app.id === "org.mediahub.windows-share" ? (
                    <Link className="primary" to="/store/windows-share">
                      {t("Set up Windows access →")}
                    </Link>
                  ) : app.id === "org.mediahub.fjordhub" ? (
                    <Link className="primary" to="/store/fjordhub">
                      {t("Set up FjordHub →")}
                    </Link>
                  ) : null}
                  {app.id === "org.mediahub.fjordhub" && (
                    <Link
                      className="button-link"
                      to="/store/fjordhub/uninstall"
                    >
                      {t("Uninstall")}
                    </Link>
                  )}
                  {installedApp && showInstalled && (
                    <AppUninstall
                      app={installedApp}
                      onRemoved={installed.reload}
                    />
                  )}
                  {app.repository && (
                    <a href={app.repository} target="_blank" rel="noreferrer">
                      {t("Source →")}
                    </a>
                  )}
                </div>
                {app.id === "org.mediahub.windows-share" ? (
                  <p className="muted">
                    {t(
                      "Uses an existing SMB share on your home network. Setup and diagnostics run on your Windows PC.",
                    )}
                  </p>
                ) : (
                  <details>
                    <summary>
                      {t("Advanced requirements and configuration")}
                    </summary>
                    {!!app.installGuide?.length && (
                      <div className="install-guide">
                        <h3>{t("Guided setup")}</h3>
                        <ol>
                          {app.installGuide.map((step) => (
                            <li key={step.id}>
                              <strong>{translateText(step.title)}</strong>
                              <p>{translateText(step.description)}</p>
                              {step.helpUrl && (
                                <a
                                  href={step.helpUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {t("Official instructions →")}
                                </a>
                              )}
                            </li>
                          ))}
                        </ol>
                        <p className="muted">
                          {t(
                            "The dedicated guided page explains every value the user must supply. Advanced previews below never change a host by themselves.",
                          )}
                        </p>
                      </div>
                    )}
                    <p>
                      {t("Runtime: ")}
                      {app.requiredRuntime}
                    </p>
                    <label>
                      {t("Target host")}
                      <select
                        value={targets[app.id] || "local"}
                        onChange={(e) => {
                          setTargets({ ...targets, [app.id]: e.target.value });
                          setPlan(undefined);
                        }}
                      >
                        {hosts.data?.map((host) => (
                          <option value={host.id} key={host.id}>
                            {host.name}
                            {host.status !== "online" ? t(" · Offline") : ""}
                            {(app.hostCapabilities || []).some(
                              (c) => !host.capabilities?.includes(c),
                            )
                              ? t(" · Missing capabilities")
                              : ""}
                          </option>
                        ))}
                      </select>
                    </label>
                    {app.recommendedIsolation === "dedicated-host" && (
                      <p className="notice">
                        {t(
                          "Dedicated host recommended. This preview never installs the app; host compatibility is checked by the Agent.",
                        )}
                      </p>
                    )}
                    <p className="muted">
                      {t("Storage:")}{" "}
                      {app.storageRequirements
                        .map((s) => `${s.type} (${s.access})`)
                        .join(", ")}
                    </p>
                    <small>{app.capabilities.join(" · ")}</small>
                    {onSelect && (
                      <label className="check-label">
                        <input
                          type="checkbox"
                          checked={selected?.includes(app.id) || false}
                          onChange={(e) =>
                            onSelect(
                              e.target.checked
                                ? [...(selected || []), app.id]
                                : (selected || []).filter(
                                    (id) => id !== app.id,
                                  ),
                            )
                          }
                        />
                        {t("Plan for later — do not install")}
                      </label>
                    )}
                    <div className="button-row">
                      <button
                        onClick={() =>
                          setExpanded(expanded === app.id ? "" : app.id)
                        }
                      >
                        {t("Configure")}
                      </button>
                      <button
                        onClick={async () => {
                          try {
                            setPlan(
                              await api(
                                "/catalog/" + app.id + "/plan",
                                "POST",
                                {
                                  logical_mappings: mappings[app.id] || {},
                                  host_id: targets[app.id] || "local",
                                },
                              ),
                            );
                            setError("");
                          } catch (e) {
                            setError((e as Error).message);
                          }
                        }}
                      >
                        {t("Preview plan")}
                      </button>
                    </div>
                    {expanded === app.id && (
                      <>
                        <ConfigurationForm app={app} />
                        <div className="dynamic-form">
                          <p className="muted">
                            {t(
                              "Storage preview mappings only. Nothing is created or mounted.",
                            )}
                          </p>
                          {app.storageRequirements.map((slot) => (
                            <label key={slot.id}>
                              {slot.id} · {slot.access}
                              {slot.required ? t(" (required)") : ""}
                              <select
                                value={mappings[app.id]?.[slot.id] || ""}
                                onChange={(e) =>
                                  setMappings({
                                    ...mappings,
                                    [app.id]: {
                                      ...mappings[app.id],
                                      [slot.id]: e.target.value,
                                    },
                                  })
                                }
                              >
                                <option value="">
                                  {t("Choose logical storage")}
                                </option>
                                {logical.data
                                  ?.filter((s) =>
                                    s.mappings.some(
                                      (m) =>
                                        m.host_id ===
                                          (targets[app.id] || "local") &&
                                        (slot.access !== "rw" ||
                                          m.access === "rw"),
                                    ),
                                  )
                                  .map((s) => (
                                    <option key={s.id} value={s.id}>
                                      {s.name}
                                    </option>
                                  ))}
                              </select>
                            </label>
                          ))}
                        </div>
                      </>
                    )}
                  </details>
                )}
              </section>
            );
          })}
        </LayoutGroup>
      )}
      {plan && (
        <Panel title={t("Installation preview — not executable")}>
          <pre className="plan-json">{JSON.stringify(plan, null, 2)}</pre>
          <button onClick={() => setPlan(undefined)}>
            {t("Close preview")}
          </button>
        </Panel>
      )}
    </div>
  );
}

export function DiscoveryPanel({
  selected,
  onSelect,
}: {
  selected: string[];
  onSelect: (ids: string[]) => void;
}) {
  const { data, error, reload } = useLoad<Discovery>("/discovery");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Panel title={t("Existing installation discovery")}>
      <ErrorBox error={error || failure} />
      <p className="muted">
        {t(
          "Read-only inspection through the agent. Environment values are never displayed. No service is changed.",
        )}
      </p>
      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await api("/discovery/scan", "POST");
            reload();
            setFailure("");
          } catch (e) {
            setFailure((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? t("Inspecting…") : t("Scan existing services")}
      </button>
      {data?.warning && (
        <div className="notice">{translateText(data.warning)}</div>
      )}
      {data?.containers.map((container) => (
        <details className="discovery-item" key={container.id}>
          <summary>
            {container.candidates.length
              ? "Possible " +
                container.candidates.map((c) => c.app).join(", ") +
                " installation"
              : container.name}
            <span className="badge">{translateText(container.status)}</span>
          </summary>
          <code>
            {container.name} · {container.image}
          </code>
          <p>
            {t("Network: ")}
            {container.networkMode} · {container.networks.join(", ")}
          </p>
          {container.mounts.map((m, i) => (
            <p key={i}>
              <code>
                {m.source} → {m.target} ({m.writable ? t("RW") : t("RO")})
              </code>
            </p>
          ))}
          <p>
            {t("Ports:")}{" "}
            {container.ports
              .map((p) => p.hostPort + " → " + p.container)
              .join(", ") || t("None published")}
          </p>
          <p>
            {t("Environment names: ")}
            {container.environmentNames.join(", ") || t("None")}
          </p>
          {container.candidates.length > 0 && (
            <label className="check-label">
              <input
                type="checkbox"
                checked={selected.includes(container.id)}
                onChange={(e) =>
                  onSelect(
                    e.target.checked
                      ? [...selected, container.id]
                      : selected.filter((id) => id !== container.id),
                  )
                }
              />
              {t("Select for future import planning")}
            </label>
          )}
        </details>
      ))}
      {data?.containers.length === 0 && (
        <p className="muted">{t("No discovery snapshot yet.")}</p>
      )}
      {data?.relationships.map((relationship, i) => (
        <p className="muted" key={i}>
          {relationship.type}: {relationship.sourceId.slice(0, 12)} →{" "}
          {relationship.targetId.slice(0, 12)}
        </p>
      ))}
    </Panel>
  );
}

export function ImportSummary() {
  const { data, error } = useLoad<ImportPlan[]>("/imports");
  return (
    <Panel title={t("Import plans")}>
      <ErrorBox error={error} />
      {data?.length ? (
        data.map((plan) => (
          <div className="import-row" key={plan.source_id}>
            <strong>{plan.detected_app}</strong>
            <span className="badge">{translateText(plan.status)}</span>
            <p>
              {plan.findings.join(" · ") ||
                t("Planning checks passed. Execution is not implemented.")}
            </p>
          </div>
        ))
      ) : (
        <p className="muted">
          {t("No existing services selected. No migration has been performed.")}
        </p>
      )}
    </Panel>
  );
}

export function SettingsExtensions({
  general,
  maintenance,
  security,
  advanced = false,
}: {
  general: ReactNode;
  maintenance: ReactNode;
  security: ReactNode;
  advanced?: boolean;
}) {
  const [tab, setTab] = useState("General");
  useEffect(() => {
    if (!advanced && ["Storage", "Network", "Agent", "Advanced"].includes(tab))
      setTab("General");
  }, [advanced, tab]);
  const network = useLoad<{ pending: NetworkConfig }>("/network");
  const [edited, setEdited] = useState<NetworkConfig>();
  const [message, setMessage] = useState("");
  return (
    <div className="stack">
      <div className="settings-tabs" role="tablist">
        {(advanced
          ? [
              "General",
              "Maintenance",
              "Storage",
              "Network",
              "Agent",
              "Security",
              "Advanced",
            ]
          : ["General", "Maintenance", "Security"]
        ).map((tabName) => (
          <button
            role="tab"
            aria-selected={tab === tabName}
            className={tab === tabName ? "active" : ""}
            key={tabName}
            onClick={() => setTab(tabName)}
          >
            {t(tabName)}
          </button>
        ))}
      </div>
      {tab === "General" && general}
      {tab === "Maintenance" && maintenance}
      {tab === "Storage" && <StorageWorkspace />}
      {tab === "Network" && (
        <LayoutGroup id="settings-network-cards">
          <Panel title={t("Network configuration")}>
            <ErrorBox error={network.error} />
            {network.data && (
              <>
                <NetworkForm
                  value={edited || network.data.pending}
                  onChange={setEdited}
                />
                <button
                  onClick={async () => {
                    try {
                      await api(
                        "/network",
                        "PUT",
                        edited || network.data?.pending,
                      );
                      setMessage(
                        "Saved as pending. Restart explicitly to activate; no firewall changes.",
                      );
                    } catch (e) {
                      setMessage((e as Error).message);
                    }
                  }}
                >
                  {t("Save network settings")}
                </button>
                <p role="status">{translateText(message)}</p>
              </>
            )}
          </Panel>
        </LayoutGroup>
      )}
      {tab === "Agent" && (
        <LayoutGroup id="settings-agent-cards">
          <div className="layout-card" data-layout-title="Agent & app runtime">
            <RuntimePanel />
          </div>
        </LayoutGroup>
      )}
      {tab === "Security" && security}
      {tab === "Advanced" && (
        <LayoutGroup id="settings-advanced-cards">
          <Panel title={t("Advanced settings")}>
            <p>
              {t(
                "Storage roots, agent token files and developer fixtures are server-side configuration only. No dangerous path override or raw Docker command endpoint is exposed.",
              )}
            </p>
          </Panel>
        </LayoutGroup>
      )}
    </div>
  );
}
