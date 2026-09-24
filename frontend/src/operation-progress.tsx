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
}: {
  operation: OperationState;
}) {
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
        aria-valuenow={progress}
      >
        <span style={{ width: `${progress}%` }} />
      </div>
      <ol className="operation-steps">
        {operation.steps.map((step, index) => (
          <li className={step.state} key={`${step.label}-${index}`}>
            <StepIcon state={step.state} />
            <span>{step.label}</span>
          </li>
        ))}
      </ol>
      {operation.details.length > 0 && (
        <details className="operation-details">
          <summary>
            <span>Technical details</span>
            <ChevronDown size={16} />
          </summary>
          <pre>{operation.details.map(redactOperationDetail).join("\n")}</pre>
        </details>
      )}
    </section>
  );
}
