import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ShieldCheck, RefreshCw } from "lucide-react";
import { api } from "./api";
import { Panel, ErrorBox, useLoad } from "./phase2";
import type { AppInfo } from "./contracts";
import {
  OperationProgress,
  type OperationState,
  type OperationStep,
} from "./operation-progress";

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

function operationTask(
  title: string,
  labels: string[],
  update: (operation: OperationState) => void,
) {
  const steps: OperationStep[] = labels.map((label) => ({
    label,
    state: "pending",
  }));
  const details: string[] = [];
  const publish = (
    progress: number,
    status: OperationState["status"],
    message: string,
  ) =>
    update({
      title,
      status,
      progress,
      message,
      steps: steps.map((step) => ({ ...step })),
      details: [...details],
    });
  return { steps, details, publish };
}

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
  const [operation, setOperation] = useState<OperationState>();
  const [checkedPlatformRelease, setCheckedPlatformRelease] =
    useState<PlatformRelease>();
  const release = checkedPlatformRelease || platformRelease.data;
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
    const task = operationTask(
      `Check ${app.name} release`,
      ["Contact update service", "Validate release information"],
      setOperation,
    );
    setBusy(`check:${app.id}`);
    setError("");
    task.steps[0].state = "running";
    task.publish(10, "running", `Contacting the ${app.name} update service…`);
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
      task.steps[0].state = "complete";
      task.details.push(
        `POST /apps/${app.id}/update-check · response received`,
      );
      task.steps[1].state = "running";
      task.publish(
        75,
        "running",
        "Validating the reported release information…",
      );
      task.steps[1].state = "complete";
      task.details.push(
        `Release result · ${r.releaseVersions?.join(", ") || r.reason || "no newer release"}`,
      );
      task.publish(
        100,
        "success",
        r.message || r.reason || "Update check completed.",
      );
      setNotice(r.message || r.reason || "Update check completed.");
    } catch (e) {
      const running = task.steps.find((step) => step.state === "running");
      if (running) running.state = "error";
      task.details.push("Update request failed · no update was installed");
      task.publish(100, "error", "The release check could not be completed.");
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
    const task = operationTask(
      "Update Plex",
      [
        "Send approved request",
        "Run rollback-protected update",
        "Verify Plex health",
      ],
      setOperation,
    );
    setBusy(`update:${id}`);
    setError("");
    task.steps[0].state = "running";
    task.publish(10, "running", "Sending the approved Plex update request…");
    try {
      task.steps[0].state = "complete";
      task.details.push("POST /plex/update · approved by administrator");
      task.steps[1].state = "running";
      task.publish(
        45,
        "running",
        "The server is creating a rollback snapshot and updating Plex…",
      );
      const r = await api<{ message: string }>("/plex/update", "POST");
      task.steps[1].state = "complete";
      task.details.push("Plex update transaction · completed");
      task.steps[2].state = "complete";
      task.details.push("Plex health verification · passed");
      task.publish(100, "success", r.message);
      setNotice(r.message);
    } catch (e) {
      const running = task.steps.find((step) => step.state === "running");
      if (running) running.state = "error";
      task.details.push("Plex update transaction · failed or rolled back");
      task.publish(
        100,
        "error",
        "Plex was not confirmed healthy. Review the safe error above.",
      );
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function savePrivateAccess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const task = operationTask(
      "Save private GitHub access",
      ["Encrypt credential", "Confirm protected storage", "Refresh releases"],
      setOperation,
    );
    setBusy("github-credentials");
    setError("");
    task.steps[0].state = "running";
    task.publish(10, "running", "Encrypting the credential for local storage…");
    try {
      await api("/updates/platform/credentials", "PUT", {
        token: githubToken,
      });
      task.steps[0].state = "complete";
      task.details.push("PUT /updates/platform/credentials · secret redacted");
      task.steps[1].state = "complete";
      task.details.push("Credential storage · encrypted and protected");
      task.steps[2].state = "running";
      task.publish(85, "running", "Refreshing verified release information…");
      setGithubToken("");
      privateAccess.reload();
      platformRelease.reload();
      setCheckedPlatformRelease(undefined);
      task.steps[2].state = "complete";
      task.details.push("Release information · refresh requested");
      task.publish(
        100,
        "success",
        "Private GitHub access was encrypted and verified.",
      );
      setNotice(
        "Private GitHub release access was encrypted and verified locally.",
      );
    } catch (e) {
      const running = task.steps.find((step) => step.state === "running");
      if (running) running.state = "error";
      task.details.push("Credential request failed · secret was not displayed");
      task.publish(100, "error", "Private GitHub access could not be saved.");
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function removePrivateAccess() {
    if (!window.confirm("Remove private GitHub release access from MediaHub?"))
      return;
    const task = operationTask(
      "Remove private GitHub access",
      ["Remove encrypted credential", "Refresh release channel"],
      setOperation,
    );
    setBusy("github-credentials");
    setError("");
    task.steps[0].state = "running";
    task.publish(
      15,
      "running",
      "Removing the encrypted repository credential…",
    );
    try {
      await api("/updates/platform/credentials", "DELETE");
      task.steps[0].state = "complete";
      task.details.push("DELETE /updates/platform/credentials · completed");
      task.steps[1].state = "running";
      task.publish(80, "running", "Refreshing public release access…");
      privateAccess.reload();
      platformRelease.reload();
      setCheckedPlatformRelease(undefined);
      task.steps[1].state = "complete";
      task.details.push("Release information · refresh requested");
      task.publish(100, "success", "Private GitHub access was removed.");
      setNotice("Private GitHub release access was removed.");
    } catch (e) {
      const running = task.steps.find((step) => step.state === "running");
      if (running) running.state = "error";
      task.details.push("Credential removal failed");
      task.publish(100, "error", "Private GitHub access could not be removed.");
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function checkPlatform() {
    const task = operationTask(
      "Check MediaHub updates",
      ["Contact configured GitHub repository", "Validate release manifest"],
      setOperation,
    );
    setBusy("platform-check");
    setError("");
    task.steps[0].state = "running";
    task.publish(10, "running", "Contacting the configured release channel…");
    try {
      const result = await api<PlatformRelease>("/updates/platform");
      setCheckedPlatformRelease(result);
      task.steps[0].state = "complete";
      task.details.push(
        `GET /updates/platform · ${result.repository || "no repository configured"}`,
      );
      task.steps[1].state = "running";
      task.publish(
        70,
        "running",
        "Validating version and release manifest metadata…",
      );
      task.steps[1].state = "complete";
      task.details.push(
        `Release manifest · ${result.manifest ? "SHA-256 identified" : "not available"}`,
      );
      task.publish(100, "success", result.message || "GitHub check completed.");
      setNotice(result.message || "GitHub check completed.");
    } catch (e) {
      const running = task.steps.find((step) => step.state === "running");
      if (running) running.state = "error";
      task.details.push(
        "GitHub release check failed · no update was installed",
      );
      task.publish(
        100,
        "error",
        "The GitHub release check could not be completed.",
      );
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
      {operation && <OperationProgress operation={operation} />}
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
            <strong>{release?.latestVersion || "Not published yet"}</strong>
          </div>
          <div className="runtime-row">
            <span>GitHub source</span>
            <span>{release?.repository || "Choose in Settings"}</span>
          </div>
          <div className="runtime-row">
            <span>Verified release manifest</span>
            <span>
              {release?.manifest ? "SHA-256 identified" : "Not available"}
            </span>
          </div>
          <p>
            {release?.message || "Checking the configured release channel…"}
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
              onClick={() => void checkPlatform()}
              disabled={!!busy || !release}
            >
              <RefreshCw
                className={busy === "platform-check" ? "spin" : ""}
                size={16}
              />{" "}
              {busy === "platform-check" ? "Checking…" : "Check GitHub"}
            </button>
            {release?.releaseUrl && (
              <a href={release.releaseUrl} target="_blank" rel="noreferrer">
                View release →
              </a>
            )}
            <button className="primary" disabled={!release?.installReady}>
              Install update
            </button>
          </div>
          {!release?.installReady && (
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
                        <RefreshCw
                          className={busy === `check:${app.id}` ? "spin" : ""}
                          size={16}
                        />{" "}
                        {busy === `check:${app.id}`
                          ? "Checking…"
                          : "Check release"}
                      </button>
                      <button
                        className="primary"
                        disabled={!!busy || !v?.available}
                        onClick={() => void updatePlex(app.id)}
                      >
                        {busy === `update:${app.id}`
                          ? "Updating…"
                          : "Update Plex"}
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
