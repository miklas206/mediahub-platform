import { useEffect, useRef } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Circle,
  LoaderCircle,
} from "lucide-react";

export type OperationStepState = "pending" | "running" | "complete" | "error";

export type OperationStep = {
  label: string;
  state: OperationStepState;
};

export type OperationState = {
  title: string;
  status: "running" | "success" | "error";
  progress: number;
  message: string;
  steps: OperationStep[];
  details: string[];
  console?: string[];
  connectionLost?: boolean;
};

export function redactOperationDetail(value: string) {
  return value
    .replace(
      /(token|password|passkey|private[_-]?key)(\s*[:=]\s*)([^&\s]+)/gi,
      "$1$2[redacted]",
    )
    .replace(/\b(?:github_pat_|gh[pousr]_)[a-z0-9_]+/gi, "[redacted]")
    .replace(/bearer\s+[a-z0-9._~+/-]+/gi, "Bearer [redacted]")
    .slice(0, 500);
}

function StepIcon({ state }: { state: OperationStepState }) {
  if (state === "complete") return <CheckCircle2 size={17} />;
  if (state === "running") return <LoaderCircle className="spin" size={17} />;
  if (state === "error") return <AlertTriangle size={17} />;
  return <Circle size={17} />;
}

export function OperationProgress({
  operation,
  activeOnly = false,
  statusOnly = false,
}: {
  operation: OperationState;
  activeOnly?: boolean;
  statusOnly?: boolean;
}) {
  const consoleView = useRef<HTMLPreElement>(null);
  const followConsole = useRef(true);
  useEffect(() => {
    if (operation.console && followConsole.current && consoleView.current)
      consoleView.current.scrollTop = consoleView.current.scrollHeight;
  }, [operation.console]);
  if (
    statusOnly ||
    (activeOnly && (operation.status !== "running" || operation.connectionLost))
  ) {
    const lines = [...operation.details, ...(operation.console || [])];
    return (
      <div className="operation-result">
        <p role={operation.status === "error" ? "alert" : "status"}>
          {operation.message}
        </p>
        {lines.length > 0 && (
          <details className="operation-details">
            <summary>
              {operation.console ? "Console" : "Technical details"}
            </summary>
            <pre aria-label={operation.console ? "Update console" : undefined}>
              {lines.map(redactOperationDetail).join("\n")}
            </pre>
          </details>
        )}
      </div>
    );
  }
  const progress = Math.max(0, Math.min(100, Math.round(operation.progress)));
  return (
    <section
      className={`operation-progress ${operation.status}`}
      role={operation.status === "error" ? "alert" : "status"}
      aria-label={`${operation.title} progress`}
      aria-live="polite"
    >
      <div className="operation-progress-heading">
        <div>
          <span className="operation-kicker">Operation</span>
          <h3>{operation.title}</h3>
          <p>{operation.message}</p>
        </div>
        <strong>{progress}%</strong>
      </div>
      <div
        className="operation-progress-track"
        role="progressbar"
        aria-label={operation.title}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={operation.connectionLost ? undefined : progress}
        aria-valuetext={
          operation.connectionLost
            ? `Last known progress: ${progress}%. Waiting for connection.`
            : undefined
        }
      >
        <span style={{ width: `${progress}%` }} />
      </div>
      {operation.connectionLost && (
        <p className="muted">
          <LoaderCircle className="spin" size={14} aria-hidden="true" />{" "}
          Reconnecting ? {progress}% and the steps below are the last received
          status.
        </p>
      )}
      <ol
        className="operation-steps"
        aria-label={
          operation.connectionLost
            ? "Last received update steps"
            : "Update steps"
        }
      >
        {operation.steps.map((step, index) => (
          <li
            className={
              operation.connectionLost && step.state === "running"
                ? "pending"
                : step.state
            }
            key={`${step.label}-${index}`}
          >
            <StepIcon
              state={
                operation.connectionLost && step.state === "running"
                  ? "pending"
                  : step.state
              }
            />
            <span>{step.label}</span>
          </li>
        ))}
      </ol>
      {(operation.details.length > 0 || operation.console) && (
        <details
          className="operation-details"
          onToggle={(event) => {
            if (
              event.currentTarget.open &&
              operation.console &&
              followConsole.current &&
              consoleView.current
            )
              consoleView.current.scrollTop = consoleView.current.scrollHeight;
          }}
        >
          <summary>
            <span>{operation.console ? "Console" : "Technical details"}</span>
            <ChevronDown size={16} />
          </summary>
          <pre
            ref={consoleView}
            onScroll={(event) => {
              const view = event.currentTarget;
              followConsole.current =
                view.scrollHeight - view.clientHeight - view.scrollTop < 24;
            }}
            aria-label={operation.console ? "Update console" : undefined}
          >
            {[...operation.details, ...(operation.console || [])]
              .map(redactOperationDetail)
              .join("\n")}
          </pre>
        </details>
      )}
    </section>
  );
}
