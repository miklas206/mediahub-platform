import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Check, Copy, Cpu, RefreshCw, X } from "lucide-react";
import { api } from "./api";
import { t } from "./i18n";
import { ErrorBox, useLoad } from "./phase2";
import { NotificationPopup } from "./notification-popup";
import { OperationProgress, type OperationState } from "./operation-progress";
import "./gpu-setup.css";

type GPU = {
  id: string;
  name: string;
  vendor: string;
  available: boolean;
  method: string;
};
type Report = {
  state: string;
  phase?: string;
  progress?: number;
  indeterminate?: boolean;
  message?: string;
  gpuId?: string;
  verified: boolean;
  details: string[];
  testedAt?: string;
};
type Status = { gpus: GPU[]; preparationRequired: boolean; test: Report };
type Draft = { hostId: string; ctid: string; gpuId: string; step: number };
const blank: Draft = { hostId: "local", ctid: "", gpuId: "", step: 0 };
const key = "mediahub-gpu-setup";

function savedDraft(): Draft {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "null");
    if (
      value &&
      typeof value.hostId === "string" &&
      value.hostId.length <= 80 &&
      typeof value.ctid === "string" &&
      value.ctid.length <= 9 &&
      typeof value.gpuId === "string" &&
      value.gpuId.length <= 80 &&
      Number.isInteger(value.step) &&
      value.step >= 0 &&
      value.step <= 3
    )
      return value;
  } catch {
    /* A disabled browser store should not prevent setup. */
  }
  return blank;
}

export function gpuPreparationCommand(ctid: string) {
  if (!/^[1-9][0-9]{2,8}$/.test(ctid)) return "";
  return `(
  set -e
  install -d -m 700 /root/mediahub-gpu-tools-v0.5.31
  for script in setup-existing-gpu.py proxmox_gpu.py gpu_setup.py; do
    curl -fsSL "https://raw.githubusercontent.com/miklas206/mediahub-platform/v0.5.31/scripts/$script" -o "/root/mediahub-gpu-tools-v0.5.31/$script"
  done
  python3 /root/mediahub-gpu-tools-v0.5.31/setup-existing-gpu.py --ctid ${ctid}
)`;
}

export function GPUSetupCard() {
  const [parameters, setParameters] = useSearchParams();
  const open = parameters.get("gpuSetup") === "1";
  const toggle = () => {
    const next = new URLSearchParams(parameters);
    if (open) next.delete("gpuSetup");
    else next.set("gpuSetup", "1");
    setParameters(next);
  };
  return (
    <section className="gpu-setup panel" aria-labelledby="gpu-setup-title">
      <div className="gpu-setup-heading">
        <div>
          <h2 id="gpu-setup-title">
            <Cpu size={22} /> {t("GPU setup")}
          </h2>
          <p className="muted">
            {t(
              "Share a GPU with MediaHub, verify hardware encoding and prepare Jellyfin.",
            )}
          </p>
        </div>
        <button onClick={toggle}>
          {open ? (
            <>
              <X size={16} />
              {t("Close guide")}
            </>
          ) : (
            t("Start GPU setup")
          )}
        </button>
      </div>
      {open && <GPUWizard />}
    </section>
  );
}

function GPUWizard() {
  const [draft, setDraft] = useState(savedDraft);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [starting, setStarting] = useState(false);
  const hosts = useLoad<{ id: string; name: string }[]>("/hosts");
  const status = useLoad<Status>(
    `/gpu-setup?host=${encodeURIComponent(draft.hostId)}`,
  );
  const report = status.data?.test;
  const gpu = status.data?.gpus.find((item) => item.id === draft.gpuId);
  const running = starting || report?.state === "running";
  const verified =
    !!gpu?.available && report?.gpuId === gpu.id && report.verified;
  const command = gpuPreparationCommand(draft.ctid);
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(draft));
    } catch {
      /* Optional resume state. */
    }
  }, [draft]);
  useEffect(() => {
    if (report?.state !== "running") return;
    const timer = setInterval(status.reload, 2000);
    return () => clearInterval(timer);
  }, [report?.state, status.reload]);
  const move = (step: number) =>
    setDraft((previous) => ({ ...previous, step }));
  const refresh = () => {
    setError("");
    status.reload();
  };
  const start = async () => {
    setError("");
    setStarting(true);
    try {
      await api("/gpu-setup/test", "POST", {
        hostId: draft.hostId,
        gpuId: draft.gpuId,
      });
      status.reload();
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setStarting(false);
    }
  };
  const copy = async () => {
    setCopied(false);
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
    } catch {
      setError(
        t(
          "Copy the displayed command manually; clipboard access is unavailable.",
        ),
      );
    }
  };
  const phases = ["preflight", "download", "container", "encode", "cleanup"];
  const index = phases.indexOf(report?.phase || "preflight");
  const operation: OperationState | undefined =
    report && report.state !== "idle"
      ? {
          title: "GPU transcoding test",
          status:
            report.state === "succeeded"
              ? "success"
              : report.state === "failed"
                ? "error"
                : "running",
          progress: report.progress || 0,
          indeterminate: report.indeterminate,
          message: report.message || "Checking GPU access",
          details: report.details || [],
          steps: [
            "Checking GPU access",
            "Downloading test image",
            "Creating test container",
            "Hardware encoding",
            "Removing test container",
          ].map((label, position) => ({
            label,
            state:
              report.state === "succeeded" || position < index
                ? "complete"
                : position === index
                  ? report.state === "failed"
                    ? "error"
                    : "running"
                  : "pending",
          })),
        }
      : undefined;
  return (
    <div className="stack">
      <ol className="wizard-steps" aria-label={t("GPU setup progress")}>
        {["MediaHub host", "Share GPU", "GPU test", "Jellyfin"].map(
          (label, step) => (
            <li
              key={label}
              aria-current={draft.step === step ? "step" : undefined}
              className={
                draft.step === step
                  ? "current"
                  : draft.step > step
                    ? "complete"
                    : ""
              }
            >
              <span>{draft.step > step ? <Check size={15} /> : step + 1}</span>
              {t(label)}
            </li>
          ),
        )}
      </ol>
      <ErrorBox error={error || status.error || hosts.error} />
      {copied && (
        <NotificationPopup tone="success">
          {t("Command copied")}
        </NotificationPopup>
      )}
      {draft.step === 0 && (
        <div className="stack">
          <h3>{t("Choose the MediaHub host that will use the GPU")}</h3>
          <label>
            {t("MediaHub host")}
            <select
              value={draft.hostId}
              disabled={running}
              onChange={(event) =>
                setDraft({ ...blank, hostId: event.target.value })
              }
            >
              <option value="local">{t("Local host")}</option>
              {hosts.data
                ?.filter((host) => host.id !== "local")
                .map((host) => (
                  <option key={host.id} value={host.id}>
                    {host.name}
                  </option>
                ))}
            </select>
          </label>
          <p>
            {t(
              "MediaHub can use only GPU devices shared with its host. This guide helps prepare an existing Proxmox LXC and tests a GPU without touching your media.",
            )}
          </p>
          <p className="muted">
            {t(
              "Already shared a GPU on a Linux Docker host? Continue and select it from the detected list.",
            )}
          </p>
          <div className="actions">
            <button className="primary" onClick={() => move(1)}>
              {t("Continue")}
            </button>
          </div>
        </div>
      )}
      {draft.step === 1 && (
        <div className="stack">
          <h3>{t("Share a GPU with this MediaHub host")}</h3>
          {!status.data?.gpus.some((item) => item.available) && (
            <div className="gpu-preparation stack">
              <p>
                {t(
                  "No ready GPU is shared with this host yet. Proxmox must grant device access before MediaHub can use it.",
                )}
              </p>
              <label>
                {t("MediaHub LXC ID")}
                <input
                  value={draft.ctid}
                  inputMode="numeric"
                  maxLength={9}
                  placeholder="107"
                  onChange={(event) => {
                    setCopied(false);
                    setDraft({ ...draft, ctid: event.target.value });
                  }}
                />
              </label>
              <p>
                {t(
                  "In Proxmox, select the node containing this LXC and open Shell. Run the command below, choose a GPU and confirm the displayed LXC. The tool stops and restarts that LXC; media and app data are preserved.",
                )}
              </p>
              {command ? (
                <>
                  <pre
                    className="gpu-command"
                    aria-label={t("Proxmox GPU preparation command")}
                  >
                    {command}
                  </pre>
                  <div className="actions">
                    <button onClick={() => void copy()}>
                      <Copy size={16} />
                      {t("Copy command")}
                    </button>
                  </div>
                </>
              ) : (
                <p className="muted">
                  {t(
                    "Enter the correct LXC ID to generate its preparation command.",
                  )}
                </p>
              )}
              <p className="muted">
                {t(
                  "Keep this guide open. When MediaHub returns, refresh detection below. The guide resumes after a browser reload.",
                )}
              </p>
            </div>
          )}
          <div className="actions">
            <button disabled={running} onClick={refresh}>
              <RefreshCw size={16} />
              {t("Refresh GPU detection")}
            </button>
          </div>
          {!status.data && !status.error && (
            <p role="status">{t("Checking GPU access")}</p>
          )}
          {status.data?.gpus.length ? (
            <fieldset className="gpu-choices">
              <legend>{t("GPU available to MediaHub")}</legend>
              {status.data.gpus.map((item) => (
                <label key={item.id} className="gpu-choice">
                  <input
                    type="radio"
                    name="gpu"
                    value={item.id}
                    checked={draft.gpuId === item.id}
                    disabled={!item.available || running}
                    onChange={() => setDraft({ ...draft, gpuId: item.id })}
                  />
                  <span>
                    <strong>{item.name}</strong>
                    <small>
                      {item.method} ·{" "}
                      {t(item.available ? "Ready for testing" : "Unavailable")}
                    </small>
                  </span>
                </label>
              ))}
            </fieldset>
          ) : null}
          <div className="actions">
            <button disabled={running} onClick={() => move(0)}>
              {t("Back")}
            </button>
            <button
              className="primary"
              disabled={!gpu?.available || running}
              onClick={() => move(2)}
            >
              {t("Continue to GPU test")}
            </button>
          </div>
        </div>
      )}
      {draft.step === 2 && (
        <div className="stack">
          <h3>{t("Verify hardware encoding")}</h3>
          <p>
            <strong>{gpu?.name || t("No GPU selected")}</strong>
            {gpu && " · " + gpu.method}
          </p>
          <p>
            {t(
              "The test downloads the official Jellyfin image and encodes ten generated frames in an isolated container. It uses no media folders, app credentials or internet access inside the test container. A failed GPU test never falls back to CPU.",
            )}
          </p>
          {operation && <OperationProgress operation={operation} />}
          <div className="actions">
            <button disabled={running} onClick={() => move(1)}>
              {t("Back")}
            </button>
            <button
              disabled={running || !gpu?.available}
              onClick={() => void start()}
            >
              {t(
                report?.state === "failed" ? "Retry GPU test" : "Run GPU test",
              )}
            </button>
            <button
              className="primary"
              disabled={!verified || running}
              onClick={() => move(3)}
            >
              {t("Continue to Jellyfin")}
            </button>
          </div>
        </div>
      )}
      {draft.step === 3 && (
        <div className="stack">
          <h3>
            {t(
              verified
                ? "GPU verified and ready for Jellyfin"
                : "Run the GPU test again",
            )}
          </h3>
          {verified ? (
            <>
              <p>
                <strong>{gpu?.name}</strong> · {gpu?.method}
              </p>
              {report?.testedAt && (
                <p className="muted">
                  {t("Last verified")}:{" "}
                  {new Date(report.testedAt).toLocaleString()}
                </p>
              )}
              <p>
                {t(
                  "The Jellyfin installer will use this host and GPU selection. After initial Jellyfin setup, open Dashboard → Playback → Transcoding, choose the matching hardware-acceleration method and save.",
                )}
              </p>
              <p className="muted">
                {t(
                  "An existing Jellyfin installation keeps its current GPU choice. This guide prepares MediaHub; it does not change an installed app automatically.",
                )}
              </p>
              <div className="actions">
                <Link
                  className="button-link primary"
                  to="/apps/install/jellyfin"
                  state={{ hostId: draft.hostId, gpuId: draft.gpuId }}
                >
                  {t("Open Jellyfin setup")}
                </Link>
                <button onClick={() => move(2)}>{t("Back to GPU test")}</button>
              </div>
            </>
          ) : (
            <>
              <p>
                {t(
                  "The host or GPU configuration changed, or MediaHub restarted. Repeat verification before continuing.",
                )}
              </p>
              <button onClick={() => move(2)}>{t("Back to GPU test")}</button>
            </>
          )}
        </div>
      )}
      <p className="muted gpu-setup-note">
        {t(
          "Your place in this guide is saved in this browser. GPU test results are confirmed by the selected host.",
        )}
      </p>
    </div>
  );
}
