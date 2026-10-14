import { t } from "./i18n";
import { OperationProgress, type OperationState } from "./operation-progress";

export function FjordHubInstallProgress({
  state,
  message,
  connectionLost = false,
}: {
  state: string;
  message: string;
  connectionLost?: boolean;
}) {
  const complete = state === "succeeded";
  const failed = ["failed", "interrupted"].includes(state);
  return (
    <OperationProgress
      operation={{
        title: t("Installing FjordHub"),
        status: complete ? "success" : failed ? "error" : "running",
        progress: complete ? 100 : 0,
        indeterminate: !complete && !failed,
        message,
        steps: [],
        details: [],
        connectionLost,
      }}
    />
  );
}

export type SeedboxTransaction = {
  state: string;
  failedStep?: string;
  steps: { id: string; state: string }[];
};

export function SeedboxInstallProgress({
  transaction,
  connectionLost = false,
}: {
  transaction: SeedboxTransaction;
  connectionLost?: boolean;
}) {
  if (!transaction.steps.length) return null;
  const complete = transaction.state === "Healthy";
  const failed =
    !complete && !["Installing", "Verifying"].includes(transaction.state);
  const current = transaction.steps.find((row) =>
    ["Running", "Failed"].includes(row.state),
  );
  const operation: OperationState = {
    title: t("Install & verify Seedbox"),
    status: complete ? "success" : failed ? "error" : "running",
    progress: complete
      ? 100
      : Math.min(
          99,
          (100 *
            transaction.steps.filter((row) => row.state === "Succeeded")
              .length) /
            transaction.steps.length,
        ),
    message: current?.id.replaceAll("_", " ") || transaction.state,
    steps: transaction.steps.map((row) => ({
      label: row.id.replaceAll("_", " "),
      state:
        row.state === "Succeeded"
          ? "complete"
          : row.state === "Failed" ||
              (failed && row.id === transaction.failedStep)
            ? "error"
            : row.state === "Running" && !failed
              ? "running"
              : "pending",
    })),
    details: [],
    connectionLost,
  };
  return <OperationProgress operation={operation} />;
}
