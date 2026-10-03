import { translateText, t } from "./i18n";

import { LayoutGroup } from "./page-layout";
import { UpdateRestartNotice } from "./update-restart-notice";
import { AgentUpdates } from "./agent-updates";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, RefreshCw, ShieldCheck } from "lucide-react";
import { api, ApiResponseError } from "./api";
import { mergeUpdateConsole } from "./update-progress";
import { ErrorBox, Panel, useLoad } from "./phase2";
import type { AppInfo } from "./contracts";
import { updateAllPlan } from "./update-all";
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
  checkStatus?: "failed";
  errorCode?: string;
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
  mainCheckIntervalSeconds?: number;
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

type QueueStatus = {
  operationId?: string;
  state: string;
  message?: string;
  progress?: number;
  coreUpdated?: boolean;
  summaryUpdated?: boolean;
  logs: string[];
  items: { name: string; state: string }[];
};
function queueOperation(job: QueueStatus): OperationState {
  return {
    title: "Update all",
    status:
      job.state === "succeeded"
        ? "success"
        : job.state === "running"
          ? "running"
          : "error",
    progress: job.progress || 0,
    message: job.message || "Updates continue on the server",
    console: job.logs,
    details: [
      "You can navigate away, refresh or close the browser. Return here to follow progress.",
    ],
    steps: job.items.map((item) => ({
      label: item.name,
      state:
        item.state === "complete"
          ? "complete"
          : item.state === "error"
            ? "error"
            : item.state === "pending"
              ? "pending"
              : "running",
    })),
  };
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
  const [actionBusy, setBusy] = useState("all-check");
  const [serverBusy, setServerBusy] = useState(true);
  const [serverError, setServerError] = useState("");
  const connectionInterrupted = useRef(false);
  function reportError(caught: unknown) {
    if (caught instanceof ApiResponseError) {
      connectionInterrupted.current = true;
      setServerError(
        "Connection interrupted. Waiting for MediaHub to respond again...",
      );
    } else {
      setError((caught as Error).message);
    }
  }
  const busy = actionBusy || (serverBusy ? "server-update" : "");
  const refreshAfterUpdate = useRef(() => {});
  const commandGeneration = useRef(0);
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
        `Update ${batchPlan.tasks.map((task) => task.name).join(", ")}? Plex playback may pause. Updates continue on the server if you leave or close this page. Core updates last.${batchPlan.manual.length ? ` Manual updates remain: ${batchPlan.manual.map((item) => item.name).join(", ")}.` : ""}`,
      )
    )
      return;
    commandGeneration.current += 1;
    setBusy("all-install");
    setError("");
    setNotice("");
    try {
      const job = await api<QueueStatus>("/updates/queue", "POST", {
        requestId: crypto.randomUUID(),
        ids: batchPlan.tasks.map((task) => task.id),
      });
      setServerBusy(job.state === "running");
      setOperations((current) => ({ ...current, batch: queueOperation(job) }));
    } catch (caught) {
      reportError(caught);
    } finally {
      setBusy("");
    }
  }

  refreshAfterUpdate.current = () => {
    platform.reload();
    privateAccess.reload();
    updateSummary.reload();
    platformRelease.reload();
    setCheckedPlatformRelease(undefined);
  };
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    let observedQueue = "";
    let observedCore = "";
    let lastQueue = "";
    async function poll() {
      const generation = commandGeneration.current;
      try {
        const [queue, core] = await Promise.all([
          api<QueueStatus>("/updates/queue"),
          api<PlatformOperation>("/updates/platform/operation"),
        ]);
        if (!active || generation !== commandGeneration.current) return;
        if (connectionInterrupted.current) {
          connectionInterrupted.current = false;
          refreshAfterUpdate.current();
        }
        setServerError("");
        const coreRunning = [
          "downloading",
          "staged",
          "building",
          "installing",
          "verifying",
          "rolling_back",
        ].includes(core.state);
        setServerBusy(queue.state === "running" || coreRunning);
        if (queue.state === "running") observedQueue = queue.operationId || "";
        if (coreRunning) observedCore = core.operationId || "";
        if (queue.state !== "idle") {
          setOperations((current) => ({
            ...current,
            batch: queueOperation(queue),
          }));
          const signature = `${queue.operationId}:${queue.state}:${queue.summaryUpdated}`;
          if (queue.state !== "running" && signature !== lastQueue)
            refreshAfterUpdate.current();
          lastQueue = signature;
        }
        if (core.state !== "idle" && core.state !== "unavailable") {
          setOperations((current) => ({
            ...current,
            platform: platformOperation(core),
          }));
        }
        if (
          (queue.state === "succeeded" &&
            queue.coreUpdated &&
            observedQueue === queue.operationId) ||
          (core.state === "succeeded" && observedCore === core.operationId)
        ) {
          window.location.reload();
          return;
        }
      } catch {
        if (active && generation === commandGeneration.current) {
          connectionInterrupted.current = true;
          setOperations((current) => ({
            ...current,
            ...Object.fromEntries(
              ["batch", "platform"].map((key) => [
                key,
                current[key]?.status === "running"
                  ? {
                      ...current[key],
                      connectionLost: true,
                      message:
                        "Connection interrupted; reconnecting to server update status...",
                    }
                  : current[key],
              ]),
            ),
          }));
          setServerError(
            "Cannot read server update status. Updates already started continue on the server; reconnecting...",
          );
        }
      } finally {
        if (active) timer = window.setTimeout(() => void poll(), 2000);
      }
    }
    void poll();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, []);

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
      reportError(caught);
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
      reportError(caught);
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
      reportError(caught);
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
      reportError(caught);
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
      reportError(caught);
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
      for (const item of result.items) {
        task.details.push(
          `${item.name}: ${item.message}${item.errorCode ? ` (${item.errorCode})` : ""}`,
        );
      }
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
      reportError(caught);
    } finally {
      setBusy("");
    }
  }

  async function installPlatform() {
    if (
      !release?.latestVersion ||
      !window.confirm(
        `Install MediaHub ${release.latestVersion}${release.latestCommit ? ` / ${release.latestCommit.slice(0, 7)} from main` : ""}? ${release.updateMethod === "source" ? "Source code will be downloaded from GitHub and built on this server while the current version keeps running. " : ""}${release.fastUpdateAvailable ? "Fast update is selected automatically when possible: Core restarts, while an unchanged Agent keeps running. Otherwise both services are rebuilt and restarted. " : "Core and the local Agent may restart. "}Configuration is backed up first, media files are excluded, and rollback is attempted if health verification fails. Remote Agents are not updated by this operation.`,
      )
    )
      return;
    commandGeneration.current += 1;
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
      setServerBusy(true);
    } catch (caught) {
      reportError(caught);
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
      reportError(caught);
    }
  }

  const updating =
    operations.platform?.status === "running" ||
    operations.batch?.status === "running";
  const restarting =
    updating &&
    Boolean(
      serverError ||
      operations.platform?.connectionLost ||
      operations.batch?.connectionLost,
    );

  return (
    <LayoutGroup id="updates-UpdatesPage-1" className="stack updates-page">
      <p className="muted">
        {t(
          "Verified updates with configuration rollback and media kept separate. Updates continue on the server if you leave, refresh or close this page. Return here to follow progress.",
        )}
      </p>
      {updating && <UpdateRestartNotice disconnected={restarting} />}
      <ErrorBox error={error || (restarting ? "" : serverError || appsError)} />
      {!restarting && (
        <ErrorBox error={platformRelease.error || updateSummary.error} />
      )}
      {notice && (
        <p className="success" role="status">
          {translateText(notice)}
        </p>
      )}
      <Panel title={t("Update overview")}>
        <div className="update-policy-heading">
          <div>
            <ShieldCheck />
            <p>
              <strong>
                {t("Full check: ")}
                {scheduleLabel(updateSummary.data?.intervalHours)}
              </strong>
            </p>
            {!!updateSummary.data?.mainCheckIntervalSeconds && (
              <p className="muted">
                {t("MediaHub checks: every")}{" "}
                {updateSummary.data.mainCheckIntervalSeconds / 60}
                {t(" min")}
              </p>
            )}
            <p className="muted">
              {t("Last checked: ")}
              {checkedAt(updateSummary.data?.checkedAt)}
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
                  className={
                    operations.batch?.status === "running" ? "spin" : ""
                  }
                />
                {operations.batch?.status === "running"
                  ? t("Updating all…")
                  : t("Update all")}
              </button>
            )}
            <button disabled={!!busy} onClick={() => void checkAll()}>
              <RefreshCw
                className={busy === "all-check" ? "spin" : ""}
                size={16}
              />{" "}
              {busy === "all-check" ? t("Checking…") : t("Check all now")}
            </button>
            <Link to="/settings">{t("Change schedule →")}</Link>
          </div>
        </div>
        <div className="update-summary-line" role="status">
          <Bell size={17} />
          <strong>
            {updateSummary.data?.count
              ? t("Updates available: {value0}", {
                  value0: updateSummary.data.items
                    .filter((item) => item.updateAvailable)
                    .map((item) => item.name)
                    .join(", "),
                })
              : !updateSummary.data?.checkedAt
                ? t("Checking update status...")
                : updateSummary.data.lastError
                  ? t("Some update sources could not be checked")
                  : t("All checked components are up to date")}
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
              {t("Dismiss notification")}
            </button>
          )}
        </div>
        {updateSummary.data?.items
          .filter((item) => item.checkStatus === "failed")
          .map((item) => (
            <p className="notice" role="alert" key={item.id}>
              <strong>{item.name}:</strong> {translateText(item.message)}
              {item.errorCode && <small> ({item.errorCode})</small>}
            </p>
          ))}
        {batchPlan.manual.length > 0 && (
          <p className="muted">
            {t("Manual update required:")}{" "}
            {batchPlan.manual.map((item) => item.name).join(", ")}
            {t(". These apps do not yet have an automatic installer.")}
          </p>
        )}
        {operations.batch?.status === "running" && (
          <p role="status">
            {t(
              "Updates continue on the server. You can leave this page. Core updates last.",
            )}
          </p>
        )}
        {operations.batch &&
          (operations.batch.status === "success" ? (
            <details>
              <summary>{t("Latest update console")}</summary>
              <OperationProgress activeOnly operation={operations.batch} />
            </details>
          ) : (
            <OperationProgress activeOnly operation={operations.batch} />
          ))}
        {operations.all && operations.all.status !== "success" && (
          <OperationProgress activeOnly statusOnly operation={operations.all} />
        )}
      </Panel>
      <LayoutGroup
        id="updates-UpdatesPage-2"
        className="apps-grid updates-grid"
      >
        <Panel title={t("MediaHub Core")}>
          <div className="runtime-row">
            <span>{t("Installed")}</span>
            <strong>
              {platform.data?.version || t("Loading…")}
              {release?.installedCommit &&
                t(" / {value0}", {
                  value0: release.installedCommit.slice(0, 7),
                })}
            </strong>
          </div>
          <div className="runtime-row">
            <span>{t("Latest code on main")}</span>
            <strong>
              {release?.latestCommit?.slice(0, 7) || t("Not checked yet")}
            </strong>
          </div>
          <div className="runtime-row">
            <span>{t("Update source")}</span>
            <span>
              {release?.installReady
                ? release.updateMethod === "source"
                  ? t("GitHub source · build locally")
                  : t("Legacy image release")
                : release?.manifest
                  ? t("Manifest verified")
                  : release?.repository || t("Choose in Settings")}
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
              {busy === "platform-check" ? t("Checking…") : t("Check GitHub")}
            </button>
            {release?.releaseUrl && (
              <a href={release.releaseUrl} target="_blank" rel="noreferrer">
                {t("View code →")}
              </a>
            )}
            <button
              className="primary"
              disabled={!!busy || !release?.installReady}
              onClick={() => void installPlatform()}
            >
              {busy === "platform-install"
                ? t("Installing…")
                : t("Install update")}
            </button>
          </div>
          {operations.platform && (
            <OperationProgress activeOnly operation={operations.platform} />
          )}
          <details className="update-card-advanced">
            <summary>{t("Details and update settings")}</summary>
            <p>
              {translateText(release?.message) ||
                t("Checking main for code changes...")}
            </p>
            <p className="muted">
              {t("Source: ")}
              {release?.repository || t("Not configured")}
              {t(". Installation")}
              {release?.updateMethod === "source"
                ? t(
                    "downloads source code and builds the required services on this server. Builds may take several minutes and need at least 8 GiB of free system space.",
                  )
                : t(
                    "requires a complete verified release and the rollback-protected host updater.",
                  )}
            </p>
            <p className="muted">
              {privateAccess.data?.configured
                ? t(
                    "Configured · the token is encrypted and is never returned to this page.",
                  )
                : t(
                    "Not configured · public repositories work without a token.",
                  )}
            </p>
            <form onSubmit={savePrivateAccess} className="inline-secret-form">
              <label>
                {t("Read-only GitHub token")}
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
                      ? t("Enter a new token to replace it")
                      : t("Fine-grained token with Contents: read")
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
                    ? t("Replace private access")
                    : t("Save private access")}
                </button>
                {privateAccess.data?.configured && (
                  <button
                    type="button"
                    disabled={busy === "github-credentials"}
                    onClick={() => void removePrivateAccess()}
                  >
                    {t("Remove access")}
                  </button>
                )}
              </div>
            </form>
            <p>
              <Link to="/backups">{t("Create configuration backup →")}</Link>
            </p>
          </details>
        </Panel>
        {apps?.some(
          (app) => !app.isMock && app.packageId === "org.mediahub.seedbox",
        ) && (
          <div className="layout-card" data-layout-title="Seedbox Agent">
            <AgentUpdates
              busy={!!busy}
              onChange={() => updateSummary.reload()}
            />
          </div>
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
                  <span>{t("Installed")}</span>
                  <strong>
                    {version?.plex?.version ||
                      version?.qBittorrent?.version ||
                      version?.cloudflare?.version ||
                      (isCloudflare
                        ? version?.available
                          ? t("Route monitoring enabled")
                          : t("Monitoring not configured")
                        : t("Not verified"))}
                  </strong>
                </div>
                {!isPlex && !isCloudflare && (
                  <div className="runtime-row">
                    <span>{t("VPN runtime")}</span>
                    <span>
                      {version?.vpn?.version || t("Pinned Gluetun image")}
                    </span>
                  </div>
                )}
                <div className="runtime-row">
                  <span>{t("Latest")}</span>
                  <span>{latest[app.id] || t("Not checked")}</span>
                </div>
                <div className="runtime-row">
                  <span>{t("Update method")}</span>
                  <span>
                    {isCloudflare
                      ? t("Official release check")
                      : isPlex
                        ? t("Managed by MediaHub")
                        : t("Coordinated fail-closed update")}
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
                          ? t("Checking…")
                          : t("Check release")}
                      </button>
                      {isPlex && (
                        <button
                          className="primary"
                          disabled={!!busy || !version?.available}
                          onClick={() => void updatePlex(app.id)}
                        >
                          {busy === `update:${app.id}`
                            ? t("Updating…")
                            : t("Update Plex")}
                        </button>
                      )}
                    </>
                  )}
                  <Link to={app.detailPath || "/apps"}>
                    {t("Open app & recovery →")}
                  </Link>
                </div>
                {operations[app.id] && (
                  <OperationProgress
                    activeOnly
                    operation={operations[app.id]!}
                  />
                )}
                {!isPlex && !isCloudflare && (
                  <details className="update-card-details">
                    <summary>{t("Update details")}</summary>
                    <p className="muted">
                      {t(
                        "VPN and torrent-client updates require a coordinated, fail-closed deployment. Routine restarts are available from the app page.",
                      )}
                    </p>
                  </details>
                )}
                {isPlex && (
                  <details className="update-card-details">
                    <summary>{t("Update details")}</summary>
                    <p className="muted">
                      {t(
                        "MediaHub checks Plex releases and creates a configuration rollback snapshot before an update. Media files stay separate.",
                      )}
                    </p>
                  </details>
                )}
                {isCloudflare && (
                  <details className="update-card-details">
                    <summary>{t("Update details")}</summary>
                    <p className="muted">
                      {t(
                        "Monitoring checks tunnel health and official Cloudflare releases. Installation guidance is available from the app page without exposing the tunnel publicly.",
                      )}
                    </p>
                  </details>
                )}
              </Panel>
            );
          })}
      </LayoutGroup>
    </LayoutGroup>
  );
}
