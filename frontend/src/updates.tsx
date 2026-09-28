import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "./api";
import { ErrorBox, Panel, useLoad } from "./phase2";
import type { AppInfo } from "./contracts";
import {
  OperationProgress,
  type OperationState,
  type OperationStep,
  type OperationStepState,
} from "./operation-progress";

type Versions = {
  plex?: { version: string | null };
  qBittorrent?: { version: string | null };
  vpn?: { version?: string | null };
  cloudflare?: { version?: string | null };
  available: boolean;
};

type ReleaseAsset = {
  name: string;
  digest: string;
  size: number;
  downloadUrl: string;
  apiUrl: string;
};

type PlatformRelease = {
  configured: boolean;
  repository: string | null;
  installedVersion: string;
  latestVersion: string | null;
  updateAvailable: boolean;
  releaseUrl: string | null;
  publishedAt: string | null;
  manifest: ReleaseAsset | null;
  assets: Record<string, ReleaseAsset>;
  installReady: boolean;
  updateMethod?: "source" | "legacy-images";
  privateAccessConfigured: boolean;
  message: string;
};

type UpdateItem = {
  id: string;
  name: string;
  installedVersion: string | null;
  latestVersion: string | null;
  updateAvailable: boolean;
  message: string;
};

type UpdateNotification = {
  id: string;
  timestamp: string;
  message: string;
  severity: string;
  state: string;
};

type UpdateSummary = {
  checkedAt: number | null;
  count: number;
  items: UpdateItem[];
  intervalHours: number;
  notifications: UpdateNotification[];
  lastError: string | null;
};

type PlatformOperation = {
  enabled: boolean;
  state: string;
  progress: number;
  message: string;
  operationId?: string | null;
  fromVersion?: string | null;
  toVersion?: string | null;
  steps?: Array<{ label?: string; state?: string }>;
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

function operationStepState(value?: string): OperationStepState {
  if (value === "running" || value === "complete" || value === "error")
    return value;
  return "pending";
}

function platformOperation(value: PlatformOperation): OperationState {
  const failed = ["failed", "rolled_back", "invalid", "unavailable"].includes(
    value.state,
  );
  return {
    title: "Install MediaHub update",
    status:
      value.state === "succeeded" ? "success" : failed ? "error" : "running",
    progress: value.progress,
    message: value.message,
    steps: (value.steps || []).map((step) => ({
      label: step.label || "Update step",
      state: operationStepState(step.state),
    })),
    details: [
      `State · ${value.state}`,
      ...(value.fromVersion && value.toVersion
        ? [`Version · ${value.fromVersion} → ${value.toVersion}`]
        : []),
    ],
  };
}

function checkedAt(value: number | null | undefined) {
  if (!value) return "Not checked yet";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value * 1000));
}

function scheduleLabel(hours: number | undefined) {
  if (!hours) return "Automatic checks are off";
  if (hours === 1) return "Every hour";
  if (hours === 24) return "Every day";
  if (hours === 168) return "Every week";
  return `Every ${hours} hours`;
}

export function UpdatesPage() {
  const apps = useLoad<AppInfo[]>("/apps");
  const platform = useLoad<{ version: string }>("/system/status");
  const platformRelease = useLoad<PlatformRelease>("/updates/platform");
  const updateSummary = useLoad<UpdateSummary>("/updates/summary");
  const privateAccess = useLoad<{ configured: boolean }>(
    "/updates/platform/credentials",
  );
  const [versions, setVersions] = useState<Record<string, Versions>>({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [latest, setLatest] = useState<Record<string, string>>({});
  const [githubToken, setGithubToken] = useState("");
  const [operations, setOperations] = useState<
    Record<string, OperationState | undefined>
  >({});
  const [checkedPlatformRelease, setCheckedPlatformRelease] =
    useState<PlatformRelease>();
  const release = checkedPlatformRelease || platformRelease.data;

  function updateOperation(key: string, operation: OperationState) {
    setOperations((current) => ({ ...current, [key]: operation }));
  }

  useEffect(() => {
    let active = true;
    for (const app of apps.data || []) {
      if (!app.detailPath) continue;
      void api<{ report: Versions }>(`/apps/${app.id}/runtime`)
        .then((result) => {
          if (active) {
            setVersions((current) => ({ ...current, [app.id]: result.report }));
          }
        })
        .catch(() => {});
    }
    return () => {
      active = false;
    };
  }, [apps.data]);

  useEffect(() => {
    const reported: Record<string, string> = {};
    for (const item of updateSummary.data?.items || []) {
      if (item.id !== "mediahub-core" && item.latestVersion)
        reported[item.id] = item.latestVersion;
    }
    if (Object.keys(reported).length)
      setLatest((current) => ({ ...current, ...reported }));
  }, [updateSummary.data]);

  async function check(app: AppInfo) {
    const task = operationTask(
      `Check ${app.name} release`,
      ["Contact update service", "Validate release information"],
      (value) => updateOperation(app.id, value),
    );
    setBusy(`check:${app.id}`);
    setError("");
    task.steps[0].state = "running";
    task.publish(10, "running", `Contacting the ${app.name} update service…`);
    try {
      const result = await api<{
        releaseVersions?: string[];
        latestVersion?: string | null;
        installedVersion?: string | null;
        supported?: boolean;
        message?: string;
        reason?: string;
      }>(`/apps/${app.id}/update-check`, "POST");
      setLatest((current) => ({
        ...current,
        [app.id]:
          result.latestVersion ||
          result.releaseVersions?.join(", ") ||
          "No newer release reported",
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
        `Release result · ${result.releaseVersions?.join(", ") || result.reason || "no newer release"}`,
      );
      task.publish(
        100,
        "success",
        result.message || result.reason || "Update check completed.",
      );
      setNotice(result.message || result.reason || "Update check completed.");
      updateSummary.reload();
    } catch (caught) {
      const running = task.steps.find((step) => step.state === "running");
      if (running) running.state = "error";
      task.details.push("Update request failed · no update was installed");
      task.publish(100, "error", "The release check could not be completed.");
      setError((caught as Error).message);
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
      (value) => updateOperation(id, value),
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
      const result = await api<{ message: string }>("/plex/update", "POST");
      task.steps[1].state = "complete";
      task.details.push("Plex update transaction · completed");
      task.steps[2].state = "complete";
      task.details.push("Plex health verification · passed");
      task.publish(100, "success", result.message);
      setNotice(result.message);
      updateSummary.reload();
    } catch (caught) {
      const running = task.steps.find((step) => step.state === "running");
      if (running) running.state = "error";
      task.details.push("Plex update transaction · failed or rolled back");
      task.publish(
        100,
        "error",
        "Plex was not confirmed healthy. Review the safe error above.",
      );
      setError((caught as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function savePrivateAccess(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const task = operationTask(
      "Save private GitHub access",
      ["Encrypt credential", "Confirm protected storage", "Refresh releases"],
      (value) => updateOperation("platform", value),
    );
    setBusy("github-credentials");
    setError("");
    task.steps[0].state = "running";
    task.publish(10, "running", "Encrypting the credential for local storage…");
    try {
      await api("/updates/platform/credentials", "PUT", { token: githubToken });
      task.steps[0].state = "complete";
      task.details.push("PUT /updates/platform/credentials · secret redacted");
      task.steps[1].state = "complete";
      task.details.push("Credential storage · encrypted and protected");
      task.steps[2].state = "running";
      task.publish(85, "running", "Refreshing verified release information…");
      setGithubToken("");
      privateAccess.reload();
      platformRelease.reload();
      updateSummary.reload();
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
    } catch (caught) {
      const running = task.steps.find((step) => step.state === "running");
      if (running) running.state = "error";
      task.details.push("Credential request failed · secret was not displayed");
      task.publish(100, "error", "Private GitHub access could not be saved.");
      setError((caught as Error).message);
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
      (value) => updateOperation("platform", value),
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
      updateSummary.reload();
      setCheckedPlatformRelease(undefined);
      task.steps[1].state = "complete";
      task.details.push("Release information · refresh requested");
      task.publish(100, "success", "Private GitHub access was removed.");
      setNotice("Private GitHub release access was removed.");
    } catch (caught) {
      const running = task.steps.find((step) => step.state === "running");
      if (running) running.state = "error";
      task.details.push("Credential removal failed");
      task.publish(100, "error", "Private GitHub access could not be removed.");
      setError((caught as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function checkPlatform() {
    const task = operationTask(
      "Check MediaHub updates",
      ["Contact configured GitHub repository", "Validate release manifest"],
      (value) => updateOperation("platform", value),
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
        "Validating version and release asset metadata…",
      );
      task.steps[1].state = "complete";
      task.details.push(
        `Release assets · ${result.installReady ? "complete and installable" : result.manifest ? "manifest verified" : "not available"}`,
      );
      task.publish(100, "success", result.message || "GitHub check completed.");
      setNotice(result.message || "GitHub check completed.");
      updateSummary.reload();
    } catch (caught) {
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
      setError((caught as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function checkAll() {
    const task = operationTask(
      "Check all updates",
      [
        "Contact verified sources",
        "Compare installed versions",
        "Create notifications",
      ],
      (value) => updateOperation("all", value),
    );
    setBusy("all-check");
    setError("");
    task.steps[0].state = "running";
    task.publish(10, "running", "Checking MediaHub and installed apps…");
    try {
      const result = await api<UpdateSummary>("/updates/check", "POST");
      task.steps[0].state = "complete";
      task.steps[1].state = "complete";
      task.steps[2].state = "complete";
      task.details.push(`${result.items.length} update sources checked`);
      task.details.push(`${result.count} verified updates available`);
      task.publish(
        100,
        "success",
        result.count
          ? `${result.count} update${result.count === 1 ? " is" : "s are"} available.`
          : "Everything checked is up to date.",
      );
      const reported: Record<string, string> = {};
      for (const item of result.items) {
        if (item.id !== "mediahub-core" && item.latestVersion)
          reported[item.id] = item.latestVersion;
      }
      setLatest((current) => ({ ...current, ...reported }));
      setNotice(
        result.count
          ? `${result.count} verified update${result.count === 1 ? " is" : "s are"} available.`
          : "Everything is up to date.",
      );
      updateSummary.reload();
      platformRelease.reload();
      setCheckedPlatformRelease(undefined);
    } catch (caught) {
      const running = task.steps.find((step) => step.state === "running");
      if (running) running.state = "error";
      task.details.push("No software was installed");
      task.publish(
        100,
        "error",
        "The complete update check could not be finished.",
      );
      setError((caught as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function waitForPlatformUpdate() {
    const deadline = Date.now() + 75 * 60 * 1000;
    while (Date.now() < deadline) {
      let result: PlatformOperation;
      try {
        result = await api<PlatformOperation>("/updates/platform/operation");
      } catch (caught) {
        if (Date.now() >= deadline) throw caught;
        updateOperation("platform", {
          title: "Install MediaHub update",
          status: "running",
          progress: 82,
          message:
            "MediaHub is restarting. Waiting for the secure health check…",
          steps: [
            { label: "Download verified release", state: "complete" },
            { label: "Back up configuration", state: "complete" },
            { label: "Replace Core and Agent", state: "running" },
            { label: "Verify health or roll back", state: "pending" },
          ],
          details: ["The browser will reconnect automatically"],
        });
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        continue;
      }
      updateOperation("platform", platformOperation(result));
      if (result.state === "succeeded") {
        setNotice(result.message);
        window.setTimeout(() => window.location.reload(), 1200);
        return;
      }
      if (
        ["failed", "rolled_back", "invalid", "unavailable"].includes(
          result.state,
        )
      ) {
        throw new Error(result.message);
      }
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
    throw new Error("The update did not complete within the safety timeout.");
  }

  async function installPlatform() {
    if (
      !release?.latestVersion ||
      !window.confirm(
        `Install MediaHub ${release.latestVersion}? ${release.updateMethod === "source" ? "Source code will be downloaded from GitHub and built on this server while the current version keeps running. " : ""}Core and the local Agent will then restart. Configuration is backed up first, media files are excluded, and rollback is attempted if health verification fails. Remote Agents are not updated by this operation.`,
      )
    )
      return;
    setBusy("platform-install");
    setError("");
    updateOperation("platform", {
      title: "Install MediaHub update",
      status: "running",
      progress: 2,
      message: "Requesting the verified release…",
      steps: [
        { label: "Download verified release", state: "running" },
        { label: "Back up configuration", state: "pending" },
        { label: "Replace Core and Agent", state: "pending" },
        { label: "Verify health or roll back", state: "pending" },
      ],
      details: ["Media storage is outside the update transaction"],
    });
    try {
      const started = await api<PlatformOperation>(
        "/updates/platform/install",
        "POST",
      );
      updateOperation("platform", platformOperation(started));
      await waitForPlatformUpdate();
    } catch (caught) {
      setError((caught as Error).message);
      setOperations((current) => {
        const existing = current.platform;
        return {
          ...current,
          platform: existing
            ? {
                ...existing,
                status: "error",
                progress: 100,
                message: (caught as Error).message,
              }
            : existing,
        };
      });
    } finally {
      setBusy("");
    }
  }

  async function dismissNotification(id: string) {
    try {
      await api(`/notifications/${encodeURIComponent(id)}/read`, "POST");
      updateSummary.reload();
    } catch (caught) {
      setError((caught as Error).message);
    }
  }

  return (
    <div className="stack">
      <p className="muted">
        Verified updates with configuration rollback and media kept separate.
      </p>
      <ErrorBox error={error || apps.error} />
      <ErrorBox error={platformRelease.error || updateSummary.error} />
      {notice && (
        <p className="success" role="status">
          {notice}
        </p>
      )}
      <Panel title="Update overview">
        <div className="update-policy-heading">
          <div>
            <ShieldCheck />
            <p>
              <strong>
                {scheduleLabel(updateSummary.data?.intervalHours)}
              </strong>
            </p>
            <p className="muted">
              Last checked: {checkedAt(updateSummary.data?.checkedAt)}
            </p>
          </div>
          <div className="button-row">
            <button disabled={!!busy} onClick={() => void checkAll()}>
              <RefreshCw
                className={busy === "all-check" ? "spin" : ""}
                size={16}
              />{" "}
              {busy === "all-check" ? "Checking…" : "Check all now"}
            </button>
            <Link to="/settings">Change schedule →</Link>
          </div>
        </div>
        {updateSummary.data?.count ? (
          <p className="update-count-summary">
            <Bell size={17} /> <strong>{updateSummary.data.count}</strong>{" "}
            update{updateSummary.data.count === 1 ? "" : "s"} available
          </p>
        ) : (
          <p className="muted">No verified updates are currently waiting.</p>
        )}
        {updateSummary.data?.notifications.map((notification) => (
          <div className="update-notification" key={notification.id}>
            <Bell size={17} />
            <div>
              <strong>{notification.message}</strong>
              <span>{new Date(notification.timestamp).toLocaleString()}</span>
            </div>
            <button onClick={() => void dismissNotification(notification.id)}>
              Dismiss
            </button>
          </div>
        ))}
        {operations.all && <OperationProgress operation={operations.all} />}
      </Panel>
      <div className="apps-grid updates-grid">
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
            <span>Release source</span>
            <span>
              {release?.installReady
                ? release.updateMethod === "source"
                  ? "GitHub source · build locally"
                  : "Legacy image release"
                : release?.manifest
                  ? "Manifest verified"
                  : release?.repository || "Choose in Settings"}
            </span>
          </div>
          <p className="update-card-message">
            {release?.message || "Checking the configured release channel…"}
          </p>
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
            <button
              className="primary"
              disabled={!!busy || !release?.installReady}
              onClick={() => void installPlatform()}
            >
              {busy === "platform-install" ? "Installing…" : "Install update"}
            </button>
          </div>
          {operations.platform && (
            <OperationProgress operation={operations.platform} />
          )}
          <details className="update-card-advanced">
            <summary>Advanced update settings</summary>
            <p className="muted">
              Source: {release?.repository || "Not configured"}. Installation
              {release?.updateMethod === "source"
                ? "downloads source code and builds Core and the local Agent on this server. Builds may take several minutes and need at least 8 GiB of free system space."
                : "requires a complete verified release and the rollback-protected host updater."}
            </p>
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
            <p>
              <Link to="/backups">Create configuration backup →</Link>
            </p>
          </details>
        </Panel>
        {apps.data
          ?.filter((app) => !app.isMock)
          .map((app) => {
            const version = versions[app.id];
            const isPlex = app.packageId === "org.mediahub.plex";
            const isCloudflare = app.packageId === "org.mediahub.cloudflared";
            return (
              <Panel key={app.id} title={app.name}>
                <div className="runtime-row">
                  <span>Installed</span>
                  <strong>
                    {version?.plex?.version ||
                      version?.qBittorrent?.version ||
                      version?.cloudflare?.version ||
                      (isCloudflare
                        ? version?.available
                          ? "Route monitoring enabled"
                          : "Monitoring not configured"
                        : "Not verified")}
                  </strong>
                </div>
                {!isPlex && !isCloudflare && (
                  <div className="runtime-row">
                    <span>VPN runtime</span>
                    <span>
                      {version?.vpn?.version || "Pinned Gluetun image"}
                    </span>
                  </div>
                )}
                <div className="runtime-row">
                  <span>Latest</span>
                  <span>{latest[app.id] || "Not checked"}</span>
                </div>
                <div className="runtime-row">
                  <span>Update method</span>
                  <span>
                    {isCloudflare
                      ? "Official release check"
                      : isPlex
                        ? "Managed by MediaHub"
                        : "Coordinated fail-closed update"}
                  </span>
                </div>
                <div className="button-row">
                  {(isPlex || isCloudflare) && (
                    <>
                      <button
                        disabled={
                          !!busy || (!isCloudflare && !version?.available)
                        }
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
                      {isPlex && (
                        <button
                          className="primary"
                          disabled={!!busy || !version?.available}
                          onClick={() => void updatePlex(app.id)}
                        >
                          {busy === `update:${app.id}`
                            ? "Updating…"
                            : "Update Plex"}
                        </button>
                      )}
                    </>
                  )}
                  <Link to={app.detailPath || "/apps"}>
                    Open app & recovery →
                  </Link>
                </div>
                {operations[app.id] && (
                  <OperationProgress operation={operations[app.id]!} />
                )}
                {!isPlex && !isCloudflare && (
                  <p className="muted update-card-message">
                    VPN and torrent-client updates require a coordinated,
                    fail-closed deployment. Routine restarts are available from
                    the app page.
                  </p>
                )}
                {isPlex && (
                  <p className="muted update-card-message">
                    MediaHub checks Plex releases and creates a configuration
                    rollback snapshot before an update. Media files stay
                    separate.
                  </p>
                )}
                {isCloudflare && (
                  <p className="muted update-card-message">
                    Monitoring checks tunnel health and official Cloudflare
                    releases. Installation guidance is available from the app
                    page without exposing the tunnel publicly.
                  </p>
                )}
              </Panel>
            );
          })}
      </div>
    </div>
  );
}
