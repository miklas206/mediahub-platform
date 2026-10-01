import { AgentUpdates } from "./agent-updates";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "./api";
import { disconnectedUpdate, mergeUpdateConsole } from "./update-progress";
import { ErrorBox, Panel, useLoad } from "./phase2";
import type { AppInfo } from "./contracts";
import { runUpdateAll, updateAllPlan } from "./update-all";
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
  installedCommit?: string | null;
  latestCommit?: string | null;
  sourceChannel?: "main";
  latestVersion: string | null;
  updateAvailable: boolean;
  releaseUrl: string | null;
  publishedAt: string | null;
  manifest: ReleaseAsset | null;
  assets: Record<string, ReleaseAsset>;
  installReady: boolean;
  updateMethod?: "source" | "legacy-images";
  fastUpdateAvailable?: boolean;
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
  logs?: string[];
  updateMode?: "fast" | "full" | null;
  updateReason?: string | null;
  changedServices?: string[];
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
    message: value.updateMode
      ? `${value.updateMode === "fast" ? "Fast update" : "Full update"} · ${value.message}`
      : value.message,
    console: value.logs || [],
    steps: (value.steps || []).map((step) => ({
      label: step.label || "Update step",
      state: operationStepState(step.state),
    })),
    details: [
      `State · ${value.state}`,
      ...(value.updateMode
        ? [
            `Update mode · ${value.updateMode === "fast" ? "Fast update" : "Full update"}`,
            ...(value.updateReason ? [value.updateReason] : []),
            ...(value.changedServices?.length
              ? [`Rebuilding · ${value.changedServices.join(", ")}`]
              : []),
          ]
        : []),
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

export function UpdatesPage({
  apps,
  appsError = "",
}: {
  apps: AppInfo[] | undefined;
  appsError?: string;
}) {
  const platform = useLoad<{ version: string }>("/system/status");
  const platformRelease = useLoad<PlatformRelease>("/updates/platform");
  const updateSummary = useLoad<UpdateSummary>("/updates/summary");
  const privateAccess = useLoad<{ configured: boolean }>(
    "/updates/platform/credentials",
  );
  const [versions, setVersions] = useState<Record<string, Versions>>({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("all-check");
  const [latest, setLatest] = useState<Record<string, string>>({});
  const [githubToken, setGithubToken] = useState("");
  const [operations, setOperations] = useState<
    Record<string, OperationState | undefined>
  >({});
  const [checkedPlatformRelease, setCheckedPlatformRelease] =
    useState<PlatformRelease>();
  const release = checkedPlatformRelease || platformRelease.data;
  const batchPlan = updateAllPlan(updateSummary.data?.items || [], apps || []);

  const checkedOnEntry = useRef(false);
  const entryCheck = useRef(checkAll);
  useEffect(() => {
    if (checkedOnEntry.current) return;
    checkedOnEntry.current = true;
    void entryCheck.current();
  }, []);

  async function installAll() {
    if (!apps || !batchPlan.tasks.length || busy) return;
    if (
      !window.confirm(
        `Update ${batchPlan.tasks.map((task) => task.name).join(", ")}? Plex playback may pause. Core updates last and reloads the page when finished.${batchPlan.manual.length ? ` Manual updates remain: ${batchPlan.manual.map((item) => item.name).join(", ")}.` : ""}`,
      )
    )
      return;
    setBusy("all-install");
    setError("");
    setNotice("");
    try {
      const outcome = await runUpdateAll(batchPlan, api, (operation) => {
        setOperations((current) => ({ ...current, batch: operation }));
      });
      if (outcome.coreUpdated && !outcome.failed) {
        window.location.reload();
        return;
      }
      await Promise.all(
        batchPlan.tasks
          .filter((task) => task.kind === "plex")
          .map(async (task) => {
            try {
              const result = await api<{ report: Versions }>(
                `/apps/${encodeURIComponent(task.id)}/runtime`,
              );
              setVersions((current) => ({
                ...current,
                [task.id]: result.report,
              }));
              await api(
                `/apps/${encodeURIComponent(task.id)}/update-check`,
                "POST",
              );
            } catch {
              setNotice(
                "The update queue has finished, but the latest app status could not be refreshed. Use Check all now to retry.",
              );
            }
          }),
      );
      if (batchPlan.tasks.some((task) => task.kind === "agent")) {
        try {
          await api("/updates/seedbox-agent");
        } catch {
          setNotice(
            "The queue finished. Check Agent update to refresh its version status.",
          );
        }
      }
      updateSummary.reload();
      platformRelease.reload();
      setCheckedPlatformRelease(undefined);
    } finally {
      setBusy("");
    }
  }

  function updateOperation(key: string, operation: OperationState) {
    setOperations((current) => ({
      ...current,
      [key]: operation.console
        ? mergeUpdateConsole(
            current[key]?.console ? current[key] : undefined,
            operation,
          )
        : operation,
    }));
  }

  useEffect(() => {
    let active = true;
    for (const app of apps || []) {
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
  }, [apps]);

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
      ["Encrypt credential", "Confirm protected storage", "Refresh source"],
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
      task.publish(85, "running", "Refreshing source information…");
      setGithubToken("");
      privateAccess.reload();
      platformRelease.reload();
      updateSummary.reload();
      setCheckedPlatformRelease(undefined);
      task.steps[2].state = "complete";
      task.details.push("Source information · refresh requested");
      task.publish(
        100,
        "success",
        "Private GitHub access was encrypted and verified.",
      );
      setNotice(
        "Private GitHub source access was encrypted and verified locally.",
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
      ["Remove encrypted credential", "Refresh main branch"],
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
      task.publish(80, "running", "Refreshing public source access…");
      privateAccess.reload();
      platformRelease.reload();
      updateSummary.reload();
      setCheckedPlatformRelease(undefined);
      task.steps[1].state = "complete";
      task.details.push("Source information · refresh requested");
      task.publish(100, "success", "Private GitHub access was removed.");
      setNotice("Private GitHub source access was removed.");
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
      ["Contact configured GitHub repository", "Check latest commit on main"],
      (value) => updateOperation("platform", value),
    );
    setBusy("platform-check");
    setError("");
    task.steps[0].state = "running";
    task.publish(10, "running", "Checking the configured repository on main…");
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
        "Comparing installed code with the latest commit…",
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
      task.details.push("GitHub code check failed · no update was installed");
      task.publish(
        100,
        "error",
        "The GitHub code check could not be completed.",
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
    setNotice("");
    task.steps[0].state = "running";
    task.publish(10, "running", "Checking MediaHub and installed apps…");
    try {
      const result = await api<UpdateSummary>("/updates/check", "POST");
      task.steps[0].state = result.lastError ? "error" : "complete";
      task.steps[1].state = "complete";
      task.steps[2].state = "complete";
      task.details.push(`${result.items.length} update sources checked`);
      task.details.push(`${result.count} verified updates available`);
      task.publish(
        100,
        result.lastError ? "error" : "success",
        result.lastError
          ? `Update check incomplete: ${result.lastError}`
          : result.count
            ? `${result.count} update${result.count === 1 ? " is" : "s are"} available.`
            : "Everything checked is up to date.",
      );
      const reported: Record<string, string> = {};
      for (const item of result.items) {
        if (item.id !== "mediahub-core" && item.latestVersion)
          reported[item.id] = item.latestVersion;
      }
      setLatest((current) => ({ ...current, ...reported }));
      if (result.lastError)
        setError(`Update check incomplete: ${result.lastError}`);
      setNotice("");
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
        setOperations((current) => ({
          ...current,
          platform: current.platform
            ? disconnectedUpdate(current.platform)
            : undefined,
        }));
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        continue;
      }
      updateOperation("platform", platformOperation(result));
      if (result.state === "succeeded") {
        setNotice(result.message);
        // Reload the document so the new frontend bundle is loaded as well.
        // This runs only after the active install completes, never on page load.
        window.location.reload();
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
        `Install MediaHub ${release.latestVersion}${release.latestCommit ? ` / ${release.latestCommit.slice(0, 7)} from main` : ""}? ${release.updateMethod === "source" ? "Source code will be downloaded from GitHub and built on this server while the current version keeps running. " : ""}${release.fastUpdateAvailable ? "Fast update is selected automatically when possible: Core restarts, while an unchanged Agent keeps running. Otherwise both services are rebuilt and restarted. " : "Core and the local Agent may restart. "}Configuration is backed up first, media files are excluded, and rollback is attempted if health verification fails. Remote Agents are not updated by this operation.`,
      )
    )
      return;
    setBusy("platform-install");
    setError("");
    updateOperation("platform", {
      title: "Install MediaHub update",
      status: "running",
      progress: 2,
      message: "Requesting the selected source commit…",
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
    <div className="stack updates-page">
      <p className="muted">
        Verified updates with configuration rollback and media kept separate.
      </p>
      <ErrorBox error={error || appsError} />
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
            {batchPlan.tasks.length > 0 && busy !== "all-check" && (
              <button
                className="primary"
                disabled={!!busy || !apps || !batchPlan.tasks.length}
                onClick={() => void installAll()}
              >
                <RefreshCw
                  size={16}
                  className={busy === "all-install" ? "spin" : ""}
                />
                {busy === "all-install" ? "Updating all…" : "Update all"}
              </button>
            )}
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
        <div className="update-summary-line" role="status">
          <Bell size={17} />
          <strong>
            {updateSummary.data?.count
              ? `Updates available: ${updateSummary.data.items
                  .filter((item) => item.updateAvailable)
                  .map((item) => item.name)
                  .join(", ")}`
              : !updateSummary.data?.checkedAt
                ? "Checking update status..."
                : updateSummary.data.lastError
                  ? "Some update sources could not be checked"
                  : "All checked components are up to date"}
          </strong>
          {!!updateSummary.data?.notifications.length && (
            <button
              className="ghost"
              onClick={() =>
                void Promise.all(
                  updateSummary.data!.notifications.map((item) =>
                    dismissNotification(item.id),
                  ),
                )
              }
            >
              Dismiss notification
            </button>
          )}
        </div>
        {batchPlan.manual.length > 0 && (
          <p className="muted">
            Manual update required:{" "}
            {batchPlan.manual.map((item) => item.name).join(", ")}. These apps
            do not yet have an automatic installer.
          </p>
        )}
        {busy === "all-install" && (
          <p role="status">
            Keep this page open while the update queue runs. Core updates last.
          </p>
        )}
        {operations.batch &&
          (operations.batch.status === "success" ? (
            <details>
              <summary>Latest update console</summary>
              <OperationProgress operation={operations.batch} />
            </details>
          ) : (
            <OperationProgress operation={operations.batch} />
          ))}
        {operations.all && operations.all.status !== "success" && (
          <OperationProgress operation={operations.all} />
        )}
      </Panel>
      <div className="apps-grid updates-grid">
        <Panel title="MediaHub Core">
          <div className="runtime-row">
            <span>Installed</span>
            <strong>
              {platform.data?.version || "Loading…"}
              {release?.installedCommit &&
                ` / ${release.installedCommit.slice(0, 7)}`}
            </strong>
          </div>
          <div className="runtime-row">
            <span>Latest code on main</span>
            <strong>
              {release?.latestCommit?.slice(0, 7) || "Not checked yet"}
            </strong>
          </div>
          <div className="runtime-row">
            <span>Update source</span>
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
                View code →
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
            <summary>Details and update settings</summary>
            <p>{release?.message || "Checking main for code changes..."}</p>
            <p className="muted">
              Source: {release?.repository || "Not configured"}. Installation
              {release?.updateMethod === "source"
                ? "downloads source code and builds the required services on this server. Builds may take several minutes and need at least 8 GiB of free system space."
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
        {apps?.some(
          (app) => !app.isMock && app.packageId === "org.mediahub.seedbox",
        ) && (
          <AgentUpdates busy={!!busy} onChange={() => updateSummary.reload()} />
        )}
        {apps
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
                  <details className="update-card-details">
                    <summary>Update details</summary>
                    <p className="muted">
                      VPN and torrent-client updates require a coordinated,
                      fail-closed deployment. Routine restarts are available
                      from the app page.
                    </p>
                  </details>
                )}
                {isPlex && (
                  <details className="update-card-details">
                    <summary>Update details</summary>
                    <p className="muted">
                      MediaHub checks Plex releases and creates a configuration
                      rollback snapshot before an update. Media files stay
                      separate.
                    </p>
                  </details>
                )}
                {isCloudflare && (
                  <details className="update-card-details">
                    <summary>Update details</summary>
                    <p className="muted">
                      Monitoring checks tunnel health and official Cloudflare
                      releases. Installation guidance is available from the app
                      page without exposing the tunnel publicly.
                    </p>
                  </details>
                )}
              </Panel>
            );
          })}
      </div>
    </div>
  );
}
