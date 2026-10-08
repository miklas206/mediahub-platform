import { useEffect, useState, type FormEvent } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { ErrorBox } from "./phase2";
import { installedFjordHubApps, type Integration } from "./integrations";
import { fjordHubAppLink } from "./fjordhub-app-link";

function AppLaunchForm({
  row,
  app,
  reload,
}: {
  row: Integration;
  app: Record<string, string | number>;
  reload: () => Promise<void>;
}) {
  const id = String(app.id);
  const saved = row.appLaunchOverrides?.[id] || "";
  const [url, setUrl] = useState(saved);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    setUrl(saved);
  }, [saved]);
  async function save(value: string | null) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(
        `/integrations/${encodeURIComponent(row.id)}/apps/${encodeURIComponent(id)}/launch-url`,
        "PUT",
        { url: value },
      );
      setUrl(value || "");
      await reload();
      window.dispatchEvent(new Event("integrations-changed"));
      setNotice(t(value ? "App launch URL saved" : "App launch URL cleared"));
    } catch (e) {
      // Do not retain a rejected credential/token URL in the browser form.
      setUrl(saved);
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    void save(url || null);
  }
  const link = fjordHubAppLink(
    row.baseUrl,
    app,
    row.appLaunchOverrides,
    row.allowHttp,
  );
  return (
    <form
      onSubmit={submit}
      className="fjordhub-launch-form stack"
      aria-label={`${String(app.name || id)} · ${t("App launch URL")}`}
    >
      <label htmlFor={`launch-${row.id}-${id}`}>
        {String(app.name || id)} · {t("App launch URL")}
      </label>
      <input
        id={`launch-${row.id}-${id}`}
        type="url"
        maxLength={500}
        autoComplete="off"
        spellCheck={false}
        value={url}
        onChange={(event) => {
          setUrl(event.target.value);
          setNotice("");
        }}
        placeholder={row.baseUrl}
        disabled={busy}
      />
      <small className="muted">
        {saved
          ? t("Custom URL")
          : link?.management
            ? t("Manage in FjordHub (app address unavailable)")
            : t("API-provided URL")}
      </small>
      <ErrorBox error={error} />
      {notice && <p role="status">{notice}</p>}
      <div className="button-row">
        <button type="submit" disabled={busy || url === saved}>
          {busy ? t("Working…") : t("Save")}
        </button>
        <button
          type="button"
          disabled={busy || !saved}
          onClick={() => void save(null)}
        >
          {t("Use default link")}
        </button>
      </div>
    </form>
  );
}

export function AppLaunchSettings({
  row,
  administrator,
  username,
  reload,
}: {
  row: Integration;
  administrator: boolean;
  username?: string;
  reload: () => Promise<void>;
}) {
  const apps = installedFjordHubApps(row);
  const missing = Object.keys(row.appLaunchOverrides || {}).filter(
    (id) => !apps.some((app) => app.id === id),
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function clear(id: string) {
    setBusy(true);
    setError("");
    try {
      await api(
        `/integrations/${encodeURIComponent(row.id)}/apps/${encodeURIComponent(id)}/launch-url`,
        "PUT",
        { url: null },
      );
      await reload();
      window.dispatchEvent(new Event("integrations-changed"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="fjordhub-settings" open>
      <summary>{t("Settings · App launch URLs")}</summary>
      <div className="stack">
        {username && (
          <p className="muted">
            {t("Signed in as")} <strong>{username}</strong>
          </p>
        )}
        <p>
          {t(
            "Local MediaHub links only. FjordHub configuration is unchanged. Use the configured FjordHub host with the actual app port or path. Other hosts, credentials, tokens, query strings and fragments are not allowed.",
          )}
        </p>
        <small className="muted">
          {row.allowHttp
            ? t(
                "HTTP is allowed by this integration’s LAN consent. Prefer HTTPS.",
              )
            : t(
                "HTTPS is required. HTTP needs explicit LAN consent on the integration.",
              )}
        </small>
        {!administrator ? (
          <p role="note">
            {t("Only administrators can change app launch URLs.")}
          </p>
        ) : (
          <>
            {!apps.length && (
              <p>{t("No installed apps reported by the API.")}</p>
            )}
            {apps.map((app) => (
              <AppLaunchForm
                key={String(app.id)}
                row={row}
                app={app}
                reload={reload}
              />
            ))}
            <ErrorBox error={error} />
            {missing.map((id) => (
              <div className="button-row" key={id}>
                <span>
                  {id} · {t("App no longer reported")}
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void clear(id)}
                >
                  {t("Use default link")}
                </button>
              </div>
            ))}
          </>
        )}
      </div>
    </details>
  );
}
