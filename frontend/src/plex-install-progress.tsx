import { t } from "./i18n";
import { OperationProgress, type OperationState } from "./operation-progress";

export type PlexInstallOperation = {
  action?: string;
  state: string;
  message?: string;
  phase?: string;
  progress?: number;
  indeterminate?: boolean;
};

export function PlexInstallProgress({
  job,
  connectionLost = false,
}: {
  job?: PlexInstallOperation;
  connectionLost?: boolean;
}) {
  if (job?.action !== "install") return null;
  const complete = job.state === "succeeded";
  const failed = job.state === "failed";
  const phases = ["preparing", "download", "storage", "container", "start"];
  const labels = [
    "Preparing installation",
    "Downloading app image",
    "Checking storage and preparing container",
    "Creating app container",
    "Starting app container",
  ];
  const phase = Math.max(0, phases.indexOf(job.phase || "preparing"));
  const operation: OperationState = {
    title: t("Install Plex"),
    status: failed ? "error" : complete ? "success" : "running",
    progress: complete ? 100 : (job.progress ?? 0),
    indeterminate:
      !failed && !complete && (job.indeterminate ?? job.progress == null),
    message: job.message || "Preparing installation",
    steps: labels.map((label, index) => ({
      label,
      state:
        complete || index < phase
          ? "complete"
          : index === phase
            ? failed
              ? "error"
              : "running"
            : "pending",
    })),
    details: [],
    connectionLost,
  };
  return <OperationProgress operation={operation} />;
}
