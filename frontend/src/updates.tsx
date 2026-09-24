import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ShieldCheck, RefreshCw } from "lucide-react";
import { api } from "./api";
import { Panel, ErrorBox, useLoad } from "./phase2";
import type { AppInfo } from "./contracts";

type Versions = {
  plex?: { version: string | null };
  qBittorrent?: { version: string | null };
  vpn?: { version?: string | null };
  available: boolean;
};
type PlatformRelease = {
  configured: boolean;
  repository: string | null;
  installedVersion: string;
  latestVersion: string | null;
  updateAvailable: boolean;
  releaseUrl: string | null;
  publishedAt: string | null;
  manifest: {
    name: string;
    digest: string;
    downloadUrl: string;
    apiUrl: string;
  } | null;
  installReady: boolean;
  privateAccessConfigured: boolean;
  message: string;
};
export function UpdatesPage() {
  const apps = useLoad<AppInfo[]>("/apps");
  const platform = useLoad<{ version: string }>("/system/status");
  const platformRelease = useLoad<PlatformRelease>("/updates/platform");
  const privateAccess = useLoad<{ configured: boolean }>(
    "/updates/platform/credentials",
  );
  const [versions, setVersions] = useState<Record<string, Versions>>({});
  const [notice, setNotice] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState("");
  const [latest, setLatest] = useState<Record<string, string>>({});
  const [githubToken, setGithubToken] = useState("");
  useEffect(() => {
    let active = true;
    for (const app of apps.data || []) {
      if (!app.detailPath) continue;
      void api<{ report: Versions }>(`/apps/${app.id}/runtime`)
        .then((r) => {
          if (active) setVersions((v) => ({ ...v, [app.id]: r.report }));
        })
        .catch(() => {});
    }
    return () => {
      active = false;
    };
  }, [apps.data]);
  async function check(app: AppInfo) {
    setBusy(app.id);
    setError("");
    try {
      const r = await api<{
        releaseVersions?: string[];
        supported?: boolean;
        message?: string;
        reason?: string;
      }>(`/apps/${app.id}/update-check`, "POST");
      setLatest((v) => ({
        ...v,
        [app.id]: r.releaseVersions?.join(", ") || "No newer release reported",
      }));
      setNotice(r.message || r.reason || "Update check completed.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function updatePlex(id: string) {
    if (
      !window.confirm(
        "Update Plex? Playback will pause. Media files are not changed; a configuration rollback snapshot is created first.",
      )
    )
      return;
    setBusy(id);
    setError("");
    try {
      const r = await api<{ message: string }>("/plex/update", "POST");
      setNotice(r.message);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function savePrivateAccess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("github-credentials");
    setError("");
    try {
      await api("/updates/platform/credentials", "PUT", {
        token: githubToken,
      });
      setGithubToken("");
      privateAccess.reload();
      platformRelease.reload();
      setNotice("Private GitHub release access was encrypted and verified locally.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function removePrivateAccess() {
    if (!window.confirm("Remove private GitHub release access from MediaHub?")) return;
    setBusy("github-credentials");
    setError("");
    try {
      await api("/updates/platform/credentials", "DELETE");
      privateAccess.reload();
      platformRelease.reload();
      setNotice("Private GitHub release access was removed.");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  return (
    <div className="stack">
      <p className="muted">
        Deliberate updates, with your media kept separate.
      </p>
      <ErrorBox error={error || apps.error} />
      <ErrorBox error={platformRelease.error} />
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <Panel title="Update policy">
        <ShieldCheck />
        <p>
          <strong>Manual approval</strong> · No background image replacement.
        </p>
        <p className="muted">
          Plex can be updated here with a rollback snapshot. Core and Seedbox
          images stay pinned until a reviewed deployment. Automatic patching
          remains disabled until that component has a verified rollback path.
        </p>
      </Panel>
      <div className="apps-grid">
        <Panel title="MediaHub Core">
          <div className="runtime-row">
            <span>Installed</span>
            <strong>{platform.data?.version || "Loading…"}</strong>
          </div>
          <div className="runtime-row">
            <span>Latest release</span>
            <strong>
              {platformRelease.data?.latestVersion || "Not published yet"}
            </strong>
          </div>
          <div className="runtime-row">
            <span>GitHub source</span>
            <span>
              {platformRelease.data?.repository || "Choose in Settings"}
            </span>
          </div>
          <div className="runtime-row">
            <span>Verified release manifest</span>
            <span>
              {platformRelease.data?.manifest
                ? "SHA-256 identified"
                : "Not available"}
            </span>
          </div>
          <p>
            {platformRelease.data?.message ||
              "Checking the configured release channel…"}
          </p>
          <div className="private-release-access">
            <h3>Private repository access</h3>
            <p className="muted">
              {privateAccess.data?.configured
                ? "Configured · the token is encrypted and is never returned to this page."
                : "Not configured · public repositories work without a token."}
            </p>
            <form onSubmit={savePrivateAccess} className="inline-secret-form">
              <label>
                Read-only GitHub token
                <input
                  type="password"
                  value={githubToken}
                  onChange={(event) => setGithubToken(event.target.value)}
                  minLength={20}
                  maxLength={512}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={
                    privateAccess.data?.configured
                      ? "Enter a new token to replace it"
                      : "Fine-grained token with Contents: read"
                  }
                  required
                />
              </label>
              <div className="button-row">
                <button
                  className="primary"
                  disabled={busy === "github-credentials" || !githubToken}
                >
                  {privateAccess.data?.configured
                    ? "Replace private access"
                    : "Save private access"}
                </button>
                {privateAccess.data?.configured && (
                  <button
                    type="button"
                    disabled={busy === "github-credentials"}
                    onClick={() => void removePrivateAccess()}
                  >
                    Remove access
                  </button>
                )}
              </div>
            </form>
          </div>
          <div className="button-row">
            <button
              onClick={platformRelease.reload}
              disabled={!platformRelease.data}
            >
              <RefreshCw size={16} /> Check GitHub
            </button>
            {platformRelease.data?.releaseUrl && (
              <a
                href={platformRelease.data.releaseUrl}
                target="_blank"
                rel="noreferrer"
              >
                View release →
              </a>
            )}
            <button
              className="primary"
              disabled={!platformRelease.data?.installReady}
            >
              Install update
            </button>
          </div>
          {!platformRelease.data?.installReady && (
            <p className="muted">
              One-click installation stays locked until the host updater has a
              tested rollback path. Public repositories need no credential;
              private repositories use the encrypted read-only access above.
            </p>
          )}
          <Link to="/backups">Create configuration backup →</Link>
        </Panel>
        {apps.data
          ?.filter((a) => !a.isMock)
          .map((app) => {
            const v = versions[app.id];
            const isPlex = app.packageId === "org.mediahub.plex";
            return (
              <Panel key={app.id} title={app.name}>
                <div className="runtime-row">
                  <span>Installed</span>
                  <strong>
                    {v?.plex?.version ||
                      v?.qBittorrent?.version ||
                      "Not verified"}
                  </strong>
                </div>
                {!isPlex && (
                  <div className="runtime-row">
                    <span>VPN runtime</span>
                    <span>{v?.vpn?.version || "Pinned Gluetun image"}</span>
                  </div>
                )}
                <div className="runtime-row">
                  <span>Latest</span>
                  <span>{latest[app.id] || "Not checked"}</span>
                </div>
                <div className="button-row">
                  {isPlex && (
                    <>
                      <button
                        disabled={!!busy || !v?.available}
                        onClick={() => void check(app)}
                      >
                        <RefreshCw size={16} /> Check release
                      </button>
                      <button
                        className="primary"
                        disabled={!!busy || !v?.available}
                        onClick={() => void updatePlex(app.id)}
                      >
                        Update Plex
                      </button>
                    </>
                  )}
                  <Link to={app.detailPath || "/apps"}>
                    Open app & recovery →
                  </Link>
                </div>
                {!isPlex && (
                  <p className="muted">
                    VPN and torrent-client updates require a coordinated,
                    fail-closed deployment. Routine restarts are available from
                    the app page.
                  </p>
                )}
              </Panel>
            );
          })}
      </div>
    </div>
  );
}
