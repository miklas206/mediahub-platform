import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import {
  ExternalLink,
  Play,
  Square,
  RotateCw,
  Check,
  Download,
} from "lucide-react";
import { api } from "./api";
import { AppUninstall } from "./app-uninstall";
import type { InstalledAppInfo } from "./contracts";
import { t, translateText } from "./i18n";
import { ErrorBox, useLoad } from "./phase2";
import { ServiceIcon } from "./service-icon";
import { OperationProgress, type OperationState } from "./operation-progress";

export const containerAppNames: Record<string, string> = {
  jellyfin: "Jellyfin",
  prowlarr: "Prowlarr",
  radarr: "Radarr",
  sonarr: "Sonarr",
  autobrr: "autobrr",
};
type Options = {
  hostId: string;
  port: number;
  slots: { id: string; required: boolean; readOnly: boolean }[];
  storage: { id: string; label: string; kind: string }[];
  gpus?: {
    id: string;
    name: string;
    vendor: string;
    available: boolean;
    method: string;
  }[];
};
type Installation = {
  app: string;
  hostId: string;
  storageIds: Record<string, string>;
  timezone: string;
  gpuId?: string;
};
type Preview = {
  planDigest: string;
  installation: Installation;
  url: string;
  mounts: { target: string; readOnly: boolean }[];
};
export type ContainerAppStatus = {
  state: string;
  url?: string;
  operation?: {
    state: string;
    message?: string;
    phase?: string;
    progress?: number;
    indeterminate?: boolean;
  };
  installation: Installation;
};

export function ContainerInstallProgress({app, status, connectionLost = false}: {app: string; status?: ContainerAppStatus; connectionLost?: boolean}) {
  const job = status?.operation;
  if (!status || (status.state !== "installing" && !["installing", "installed", "failed"].includes(job?.state || ""))) return null;
  const phases = ["preparing", "download", "storage", "container", "start"];
  const labels = ["Preparing installation", "Downloading app image", "Checking storage and preparing container", "Creating app container", "Starting app container"];
  const failed = job?.state === "failed";
  const complete = job?.state === "installed";
  const index = phases.indexOf(job?.phase || "download");
  const operation: OperationState = {
    title: t("Install {value0}", {value0: containerAppNames[app] || app}),
    status: failed ? "error" : complete ? "success" : "running",
    progress: complete ? 100 : job?.progress || 0,
    indeterminate: !failed && !complete && (job?.indeterminate ?? job?.progress == null),
    message: job?.message || "Downloading and starting container",
    steps: labels.map((label, step) => ({label, state: complete || step < index ? "complete" : step === index ? failed ? "error" : "running" : "pending"})),
    details: [],
    connectionLost,
  };
  return <OperationProgress operation={operation} />;
}

export function ContainerAppPage() {
  const { containerApp = "" } = useParams();
  if (!Object.hasOwn(containerAppNames, containerApp))
    return <ErrorBox error={t("App not found")} />;
  return <ContainerAppSetup key={containerApp} app={containerApp} />;
}

export function ContainerAppSetup({ app }: { app: string }) {
  const suggested = useLocation().state as {hostId?: string; gpuId?: string} | null;
  const hosts = useLoad<{ id: string; name: string }[]>("/hosts");
  const installed = useLoad<InstalledAppInfo[]>("/apps?include_health=false");
  const registered = installed.data?.find(
    (item) => item.packageId === "org.mediahub." + app,
  );
  const [host, setHost] = useState(suggested?.hostId || "local");
  const [storage, setStorage] = useState<Record<string, string>>({});
  const [timezone, setTimezone] = useState("Europe/Copenhagen");
  const [gpuId, setGpuId] = useState(app === "jellyfin" ? suggested?.gpuId || "" : "");
  const [preview, setPreview] = useState<Preview>();
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [status, setStatus] = useState<ContainerAppStatus>();
  const [refresh, setRefresh] = useState(0);
  const options = useLoad<Options>(
    `/container-apps/${app}/install-options?host=${encodeURIComponent(host)}`,
  );
  const needsStatus = !!registered || accepted;
  useEffect(() => {
    if (!needsStatus) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const report = await api<ContainerAppStatus>(
          `/container-apps/${app}/status`,
          "GET",
          undefined,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setStatus(report);
          setError("");
        }
      } catch (failure) {
        if (!controller.signal.aborted) setError((failure as Error).message);
      } finally {
        if (!controller.signal.aborted)
          timer = setTimeout(() => void poll(), 3000);
      }
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [app, needsStatus, refresh]);
  const change = (slot: string, value: string) => {
    setStorage({ ...storage, [slot]: value });
    setPreview(undefined);
  };
  const review = async () => {
    setBusy(true);
    setError("");
    try {
      setPreview(
        await api<Preview>("/container-apps/install-plan", "POST", {
          app,
          hostId: host,
          storageIds: Object.fromEntries(
            Object.entries(storage).filter(([, value]) => value),
          ),
          timezone,
          ...(gpuId ? { gpuId } : {}),
        }),
      );
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const install = async () => {
    if (!preview) return;
    setBusy(true);
    setStarting(true);
    setError("");
    try {
      await api("/container-apps/install", "POST", {
        installation: preview.installation,
        confirmedPlanDigest: preview.planDigest,
      });
      setAccepted(true);
      setStatus({
        state: "installing",
        installation: preview.installation,
        operation: {
          state: "installing",
          phase: "preparing",
          progress: 5,
          message: "Preparing installation",
        },
      });
      installed.reload();
      setRefresh((value) => value + 1);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
      setStarting(false);
    }
  };
  const action = async (command: string) => {
    if (!registered) return;
    setBusy(true);
    setError("");
    try {
      await api(`/apps/${registered.id}/actions/${command}`, "POST");
      setRefresh((value) => value + 1);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const failed = ["failed", "not-installed", "removed"].includes(
    status?.state || "",
  );
  const showSetup = !needsStatus || failed;
  const ready =
    !!options.data &&
    (!gpuId ||
      options.data.gpus?.some((gpu) => gpu.id === gpuId && gpu.available)) &&
    options.data.slots.every((slot) => !slot.required || storage[slot.id]);
  const running = status?.state === "running";
  return (
    <div className="stack app-install-page">
      <Link to="/">{t("Back to MediaHub")}</Link>
      <header>
        <h1>
          <ServiceIcon packageId={"org.mediahub." + app} size={28} />{" "}
          {containerAppNames[app]}
        </h1>
      </header>
      <ErrorBox
        error={
          error ||
          installed.error ||
          hosts.error ||
          (showSetup ? options.error : "")
        }
      />
      {starting && (
        <ContainerInstallProgress app={app} status={{state: "installing", installation: preview!.installation, operation: {state: "installing", phase: "preparing", indeterminate: true, message: "Preparing installation"}}} />
      )}
      {needsStatus && !starting && (
        <section className="phase-content" aria-label={t("Container status")}>
          <h2>{t("Container status")}</h2>
          <ContainerInstallProgress app={app} status={status} connectionLost={!!error && status?.state === "installing"} />
          {status?.installation.gpuId && (
            <p>
              {t(
                "GPU access is configured. In Jellyfin Dashboard → Playback → Transcoding, select NVIDIA NVENC, Intel QSV or VAAPI to match your GPU, then save.",
              )}
            </p>
          )}
          <p role="status">
            {translateText(
              status?.operation?.state === "failed"
                ? status.operation.message
                : {
                    running: "Container running",
                    stopped: "Container stopped",
                    installing: "Installing container",
                    failed: "Installation failed",
                    removed: "Container removed",
                    "not-installed": "Container not installed",
                  }[status?.state || ""] || "Checking container status...",
            )}
          </p>
          <div className="actions">
            {running && status?.url && (
              <a
                className="button-link primary"
                href={status.url}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink size={16} /> {t("Open ")}
                {containerAppNames[app]}
              </a>
            )}
            {registered && !failed && (
              <>
                <button
                  disabled={busy || status?.state !== "stopped"}
                  onClick={() => void action("start")}
                >
                  <Play size={16} /> {t("Start")}
                </button>
                <button
                  disabled={busy || !running}
                  onClick={() => void action("stop")}
                >
                  <Square size={16} /> {t("Stop")}
                </button>
                <button
                  disabled={busy || !running}
                  onClick={() => void action("restart")}
                >
                  <RotateCw size={16} /> {t("Restart")}
                </button>
              </>
            )}
            {registered && status?.state !== "installing" && (
              <AppUninstall
                app={registered}
                onRemoved={() => {
                  setAccepted(false);
                  setStatus(undefined);
                  installed.reload();
                }}
              />
            )}
          </div>
        </section>
      )}
      {showSetup && (
        <>
          <section className="phase-content">
            <h2>{t("Installation")}</h2>
            <div className="dynamic-form">
              <label>
                {t("Target host")}
                <select
                  value={host}
                  disabled={busy}
                  onChange={(event) => {
                    setHost(event.target.value);
                    setStorage({});
                    setGpuId("");
                    setPreview(undefined);
                  }}
                >
                  <option value="local">{t("Local host")}</option>
                  {hosts.data
                    ?.filter((item) => item.id !== "local")
                    .map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                </select>
              </label>
              {options.data?.slots.map((slot) => (
                <label key={slot.id}>
                  {t(
                    {
                      appdata: "App data storage",
                      movies: "Movies",
                      tv: "TV shows",
                      downloads: "Downloads",
                    }[slot.id] || slot.id,
                  )}
                  {slot.required ? " *" : ""}
                  <select
                    value={storage[slot.id] || ""}
                    disabled={busy}
                    onChange={(event) => change(slot.id, event.target.value)}
                  >
                    <option value="">
                      {t(slot.required ? "Choose storage" : "None")}
                    </option>
                    {options.data?.storage
                      .filter((item) => item.kind === slot.id)
                      .map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.label}
                        </option>
                      ))}
                  </select>
                </label>
              ))}
              {app === "jellyfin" && (
                <label>
                  {t("GPU transcoding")}
                  <select
                    value={gpuId}
                    disabled={busy}
                    onChange={(event) => {
                      setGpuId(event.target.value);
                      setPreview(undefined);
                    }}
                  >
                    <option value="">{t("CPU only (no GPU)")}</option>
                    {options.data?.gpus?.map((gpu) => (
                      <option
                        key={gpu.id}
                        value={gpu.id}
                        disabled={!gpu.available}
                      >
                        {gpu.name} · {gpu.method}
                        {!gpu.available ? " · " + t("Unavailable") : ""}
                      </option>
                    ))}
                  </select>
                  <small>
                    {t(
                      "Only GPUs shared with this MediaHub host are listed. Prepare GPU access in the Proxmox installation guide first.",
                    )}
                  </small>
                  <Link to="/settings?section=General&gpuSetup=1">{t("Open GPU setup guide")}</Link>
                </label>
              )}
              <label>
                {t("Timezone")}
                <input
                  value={timezone}
                  maxLength={80}
                  disabled={busy}
                  onChange={(event) => {
                    setTimezone(event.target.value);
                    setPreview(undefined);
                  }}
                />
              </label>
            </div>
            <button disabled={busy || !ready} onClick={() => void review()}>
              <Check size={16} /> {t("Review installation")}
            </button>
          </section>
          {preview && (
            <section className="phase-content">
              <h2>{t("Installation preview")}</h2>
              <dl>
                <dt>{t("Target host")}</dt>
                <dd>{preview.installation.hostId}</dd>
                <dt>{t("Address")}</dt>
                <dd>{preview.url}</dd>
                {app === "jellyfin" && (
                  <>
                    <dt>{t("GPU transcoding")}</dt>
                    <dd>
                      {options.data?.gpus?.find(
                        (gpu) => gpu.id === preview.installation.gpuId,
                      )?.name || t("CPU only (no GPU)")}
                    </dd>
                  </>
                )}
              </dl>
              <table>
                <thead>
                  <tr>
                    <th>{t("Container path")}</th>
                    <th>{t("Access")}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.mounts.map((mount) => (
                    <tr key={mount.target}>
                      <td>{mount.target}</td>
                      <td>{t(mount.readOnly ? "Read only" : "Read/write")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button
                className="primary"
                disabled={busy}
                onClick={() => void install()}
              >
                <Download size={16} /> {t("Install ")}
                {containerAppNames[app]}
              </button>
            </section>
          )}
        </>
      )}
    </div>
  );
}
