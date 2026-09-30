import type { AppInfo } from "./contracts";
import {
  redactOperationDetail,
  type OperationState,
} from "./operation-progress";

export type AvailableUpdate = {
  id: string;
  name: string;
  updateAvailable: boolean;
};
type Task = AvailableUpdate & { kind: "plex" | "core" | "agent" };
export function updateAllPlan(items: AvailableUpdate[], apps: AppInfo[]) {
  const tasks: Task[] = [];
  const manual: AvailableUpdate[] = [];
  for (const item of items.filter((item) => item.updateAvailable)) {
    if (item.id === "mediahub-core") tasks.push({ ...item, kind: "core" });
    else if (item.id === "seedbox-agent")
      tasks.push({ ...item, kind: "agent" });
    else if (
      apps.some(
        (app) =>
          app.id === item.id &&
          !app.isMock &&
          app.packageId === "org.mediahub.plex",
      )
    )
      tasks.push({ ...item, kind: "plex" });
    else manual.push(item);
  }
  tasks.sort((a, b) => Number(a.kind === "core") - Number(b.kind === "core"));
  return { tasks, manual };
}

type Request = <T>(path: string, method?: string) => Promise<T>;
type Status = {
  state: string;
  message: string;
  operationId?: string;
  logs?: string[];
};

export async function runUpdateAll(
  plan: ReturnType<typeof updateAllPlan>,
  request: Request,
  publish: (state: OperationState) => void,
  pause = () => new Promise<void>((resolve) => setTimeout(resolve, 2000)),
) {
  const state: OperationState = {
    title: "Update all",
    status: "running",
    progress: 0,
    message: "Starting update queue",
    details: [],
    console: [],
    steps: plan.tasks.map((task) => ({ label: task.name, state: "pending" })),
  };
  const log = (message: string) => {
    const line = redactOperationDetail(message);
    if (state.console?.at(-1) !== line)
      state.console = [...(state.console || []), line].slice(-200);
    state.message = line;
    publish({
      ...state,
      steps: state.steps.map((step) => ({ ...step })),
      console: [...(state.console || [])],
    });
  };
  for (const item of plan.manual)
    log(
      `${item.name}: manual update required; no automatic installer is available.`,
    );
  let coreUpdated = false;
  for (const [index, task] of plan.tasks.entries()) {
    state.steps[index].state = "running";
    state.progress = Math.round((index / plan.tasks.length) * 100);
    log(`${task.name}: checking whether an update is still available…`);
    try {
      const check = await request<{
        updateAvailable?: boolean;
        installReady?: boolean;
        releaseVersions?: string[];
        supported?: boolean;
      }>(
        task.kind === "core"
          ? "/updates/platform"
          : task.kind === "agent"
            ? "/updates/seedbox-agent"
            : `/apps/${encodeURIComponent(task.id)}/update-check`,
        task.kind !== "plex" ? "GET" : "POST",
      );
      const available =
        check.supported === false
          ? undefined
          : (check.updateAvailable ??
            (Array.isArray(check.releaseVersions)
              ? check.releaseVersions.length > 0
              : undefined));
      if (available === false) {
        state.steps[index].state = "complete";
        log(`${task.name}: already up to date; skipped.`);
        continue;
      }
      if (available !== true)
        throw Error("The update could not be verified; nothing was installed.");
      if (task.kind === "agent" && !check.installReady)
        throw Error(
          "Prepare SSH in the Seedbox Agent card before starting Update all.",
        );
      if (task.kind === "core" && !check.installReady)
        throw Error("Core updater is not ready for installation.");
      log(`${task.name}: starting update. Waiting for verified completion…`);
      const started = await request<Status>(
        task.kind === "core"
          ? "/updates/platform/install"
          : task.kind === "agent"
            ? "/updates/seedbox-agent/install"
            : "/plex/update",
        "POST",
      );
      let current = started;
      const deadline = Date.now() + 75 * 60 * 1000;
      const seen = new Set<string>();
      while (true) {
        for (const line of current.logs || []) {
          if (!seen.has(line)) {
            seen.add(line);
            log(`${task.name}: ${line}`);
          }
        }
        if (current.message) log(`${task.name}: ${current.message}`);
        if (current.state === "succeeded") break;
        if (
          [
            "failed",
            "rolled_back",
            "interrupted",
            "invalid",
            "unavailable",
            "idle",
          ].includes(current.state)
        )
          throw Error(
            current.message || "Update was not confirmed successful.",
          );
        if (Date.now() >= deadline)
          throw Error(
            "Timed out waiting for update completion. Inspect the app before retrying.",
          );
        await pause();
        try {
          const next =
            task.kind === "core"
              ? await request<Status>("/updates/platform/operation")
              : task.kind === "agent"
                ? await request<Status>("/updates/seedbox-agent/operation")
                : (
                    await request<{ report: { operation: Status } }>(
                      `/apps/${encodeURIComponent(task.id)}/runtime`,
                    )
                  ).report.operation;
          if (!next) throw Error("Update status unavailable");
          if (
            task.kind !== "plex" &&
            started.operationId &&
            next.operationId !== started.operationId
          ) {
            log(`${task.name}: waiting for this operation's status…`);
            continue;
          }
          current = next;
        } catch {
          log(
            `${task.name}: connection interrupted; waiting for status. The install request will not be repeated.`,
          );
        }
      }
      state.steps[index].state = "complete";
      coreUpdated ||= task.kind === "core";
      log(`${task.name}: update completed successfully.`);
    } catch (error) {
      state.steps[index].state = "error";
      state.status = "error";
      log(
        `${task.name}: ${(error as Error).message} Queue stopped; remaining updates were not started.`,
      );
      return { coreUpdated, failed: true };
    }
  }
  state.progress = 100;
  state.status = "success";
  log(
    plan.manual.length
      ? "Automatic updates complete. The listed manual updates are still outstanding."
      : "All available updates completed.",
  );
  return { coreUpdated, failed: false };
}
