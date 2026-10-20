import { useEffect, useState } from "react";
import { FolderOpen, Plus, Save, Trash2, ArrowUp } from "lucide-react";
import { api } from "./api";
import { useData } from "./use-data";
import { t } from "./i18n";
import { NotificationPopup } from "./notification-popup";
import { useConfirm } from "./confirmation-dialog";
import "./plex-libraries.css";

type Root = { path: string };
export type PlexLibrary = {
  id: string;
  name: string;
  type: string;
  locations: string[];
  revision: string;
};
type Inventory = {
  available: boolean;
  message?: string;
  roots: Root[];
  libraries: PlexLibrary[];
};
type Folders = {
  path: string;
  folders: { path: string; name: string }[];
  truncated: boolean;
};

function FolderChooser({
  roots,
  disabled,
  add,
}: {
  roots: Root[];
  disabled: boolean;
  add: (path: string) => void;
}) {
  const [root, setRoot] = useState("");
  const [path, setPath] = useState("");
  const [folders, setFolders] = useState<Folders>();
  const [error, setError] = useState("");
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    setError("");
    setFolders(undefined);
    void api<Folders>(
      `/plex/library-folders?path=${encodeURIComponent(path)}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setFolders(value);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [path]);
  return (
    <div className="plex-folder-chooser">
      {error && <NotificationPopup tone="danger">{t(error)}</NotificationPopup>}
      <label>
        {t("Assigned media storage")}
        <select
          disabled={disabled}
          value={root}
          onChange={(event) => {
            setRoot(event.target.value);
            setPath(event.target.value);
          }}
        >
          <option value="">{t("Choose storage")}</option>
          {roots.map((row) => (
            <option key={row.path} value={row.path}>
              {row.path}
            </option>
          ))}
        </select>
      </label>
      {path && (
        <>
          <code className="plex-folder-path">{path}</code>
          <div className="button-row">
            <button
              type="button"
              disabled={disabled || path === root}
              onClick={() => setPath(path.slice(0, path.lastIndexOf("/")))}
            >
              <ArrowUp size={16} />
              {t("Parent folder")}
            </button>
            <button
              type="button"
              disabled={disabled || folders?.path !== path}
              onClick={() => add(path)}
            >
              <Plus size={16} />
              {t("Use this folder")}
            </button>
          </div>
          <label>
            {t("Open a subfolder")}
            <select
              value=""
              disabled={disabled || folders?.path !== path}
              onChange={(event) => {
                if (event.target.value) setPath(event.target.value);
              }}
            >
              <option value="">
                {t(folders?.path === path ? "Choose a subfolder" : "Loading…")}
              </option>
              {folders?.path === path &&
                folders.folders.map((row) => (
                  <option key={row.path} value={row.path}>
                    {row.name}
                  </option>
                ))}
            </select>
          </label>
          {folders?.truncated && (
            <p className="muted">{t("Only the first 200 folders are shown")}</p>
          )}
        </>
      )}
    </div>
  );
}

export function PlexLibraryPaths({
  paths,
  disabled,
  remove,
}: {
  paths: string[];
  disabled?: boolean;
  remove?: (path: string) => void;
}) {
  return (
    <ul className="plex-library-paths">
      {paths.map((path) => (
        <li key={path}>
          <code>{path}</code>
          {remove && (
            <button
              type="button"
              disabled={disabled}
              aria-label={`${t("Remove folder")}: ${path}`}
              onClick={() => remove(path)}
            >
              <Trash2 size={16} />
              {t("Remove folder")}
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

function LibraryCard({
  library,
  roots,
  busy,
  mutate,
}: {
  library: PlexLibrary;
  roots: Root[];
  busy: boolean;
  mutate: (
    method: "PUT" | "DELETE",
    id: string,
    value: unknown,
  ) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState<{
    locations: string[];
    revision: string;
  } | null>(null);
  const confirm = useConfirm();
  const removeLibrary = async () => {
    if (
      await confirm(
        t(
          "Remove this Plex library? Its indexed metadata and library settings will be removed. Media files stay untouched.",
        ),
        { danger: true },
      )
    ) {
      if (
        await mutate("DELETE", library.id, {
          expectedRevision: draft?.revision || library.revision,
          confirmRemove: true,
        })
      )
        setDraft(null);
    }
  };
  return (
    <article className="plex-library-card" aria-label={library.name}>
      <div className="panel-heading">
        <h3>{library.name}</h3>
        <span className="muted">
          {t(
            library.type === "show"
              ? "TV shows"
              : library.type === "movie"
                ? "Movies"
                : library.type,
          )}
        </span>
      </div>
      <PlexLibraryPaths
        paths={draft?.locations || library.locations}
        disabled={busy}
        remove={
          draft
            ? (path) =>
                setDraft({
                  ...draft,
                  locations: draft.locations.filter((value) => value !== path),
                })
            : undefined
        }
      />
      {draft ? (
        <>
          <FolderChooser
            roots={roots}
            disabled={busy}
            add={(path) =>
              setDraft({
                ...draft,
                locations: [...new Set([...draft.locations, path])],
              })
            }
          />
          {!draft.locations.length && (
            <p className="muted">
              {t(
                "A library needs at least one folder. Use Remove library to remove the library and its metadata.",
              )}
            </p>
          )}
          <div className="button-row">
            <button
              type="button"
              className="primary"
              disabled={busy || !draft.locations.length}
              onClick={async () => {
                if (
                  await mutate("PUT", library.id, {
                    expectedRevision: draft.revision,
                    locations: draft.locations,
                  })
                )
                  setDraft(null);
              }}
            >
              <Save size={16} />
              {t("Save folders")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setDraft(null)}
            >
              {t("Cancel")}
            </button>
          </div>
        </>
      ) : (
        <button
          type="button"
          disabled={busy}
          onClick={() =>
            setDraft({
              locations: [...library.locations],
              revision: library.revision,
            })
          }
        >
          <FolderOpen size={16} />
          {t("Edit folders")}
        </button>
      )}
      <button
        type="button"
        className="plex-library-remove"
        disabled={busy}
        onClick={() => void removeLibrary()}
      >
        <Trash2 size={16} />
        {t("Remove library")}
      </button>
    </article>
  );
}

export function PlexLibrarySettings() {
  const { data, error, reload } = useData<Inventory>("/plex/libraries");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ message: string; error: boolean }>();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("movies");
  const [locations, setLocations] = useState<string[]>([]);
  async function mutate(
    method: "POST" | "PUT" | "DELETE",
    id: string,
    value: unknown,
  ) {
    setBusy(true);
    setNotice(undefined);
    try {
      await api(`/plex/libraries${id ? `/${id}` : ""}`, method, value);
      setNotice({
        message: t("Plex libraries saved. Media files are preserved."),
        error: false,
      });
      reload();
      window.dispatchEvent(new Event("apps-changed"));
      return true;
    } catch (failure) {
      setNotice({ message: t((failure as Error).message), error: true });
      return false;
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel plex-library-settings">
      {(notice?.error || error) && (
        <NotificationPopup tone="danger">
          {t((notice?.error ? notice.message : error) || "")}
        </NotificationPopup>
      )}
      {notice && !notice.error && (
        <NotificationPopup tone="success">{notice.message}</NotificationPopup>
      )}
      <div className="panel-heading">
        <h2>
          <FolderOpen size={20} />
          {t("Plex libraries and folders")}
        </h2>
        <button disabled={busy} onClick={reload}>
          {t("Refresh libraries")}
        </button>
      </div>
      <div className="phase-content">
        <p className="muted">
          {t(
            "These are Plex's current libraries. Add or remove folders here; changes made in Plex are preserved after a MediaHub restart.",
          )}
        </p>
        <p className="muted">
          {t(
            "Attach additional NAS storage below before choosing its folders. Library folder changes do not restart Plex or move media files.",
          )}
        </p>
        {!data && !error && <p role="status">{t("Loading…")}</p>}
        {data && !data.available && (
          <p>
            {t(
              data.message ||
                "Start Plex in MediaHub to edit its libraries and folders",
            )}
          </p>
        )}
        {data?.available && (
          <>
            <div className="plex-library-grid">
              {data.libraries.map((library) => (
                <LibraryCard
                  key={library.id}
                  library={library}
                  roots={data.roots}
                  busy={busy}
                  mutate={mutate}
                />
              ))}
            </div>
            {!data.libraries.length && (
              <p>
                {t(
                  "No Plex libraries yet. Create one and choose its media folders.",
                )}
              </p>
            )}
            {creating ? (
              <form
                className="settings-form plex-library-create"
                onSubmit={async (event) => {
                  event.preventDefault();
                  if (
                    await mutate("POST", "", {
                      name: name.trim(),
                      kind,
                      locations,
                    })
                  ) {
                    setCreating(false);
                    setName("");
                    setLocations([]);
                  }
                }}
              >
                <h3>{t("Create Plex library")}</h3>
                <label>
                  {t("Library name")}
                  <input
                    required
                    maxLength={80}
                    disabled={busy}
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                  />
                </label>
                <label>
                  {t("Library type")}
                  <select
                    disabled={busy}
                    value={kind}
                    onChange={(event) => setKind(event.target.value)}
                  >
                    <option value="movies">{t("Movies")}</option>
                    <option value="tv">{t("TV shows")}</option>
                    <option value="other">{t("Other Media")}</option>
                  </select>
                </label>
                <PlexLibraryPaths
                  paths={locations}
                  disabled={busy}
                  remove={(path) =>
                    setLocations(locations.filter((value) => value !== path))
                  }
                />
                <FolderChooser
                  roots={data.roots}
                  disabled={busy}
                  add={(path) =>
                    setLocations([...new Set([...locations, path])])
                  }
                />
                <div className="button-row">
                  <button
                    type="submit"
                    className="primary"
                    disabled={busy || !name.trim() || !locations.length}
                  >
                    {t("Create library")}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setCreating(false)}
                  >
                    {t("Cancel")}
                  </button>
                </div>
              </form>
            ) : (
              <button
                type="button"
                disabled={busy || !data.roots.length}
                onClick={() => setCreating(true)}
              >
                <Plus size={16} />
                {t("Create Plex library")}
              </button>
            )}
            {!data.roots.length && (
              <p>
                {t(
                  "Attach approved media storage before adding library folders.",
                )}
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}
