import { useState, type ReactNode } from "react";
import { Activity, History, Cpu } from "lucide-react";
import type { Runtime } from "./runtime";
import { PlexGPUHistory, PlexGPUSessions } from "./plex-gpu-sessions";
import { Panel } from "./phase2";
import { t } from "./i18n";
import { safeAppUrl } from "./app-uptime";

export function PlexGPUPanel({
  report,
  extraCards,
}: {
  report: Runtime;
  appId?: string;
  extraCards?: ReactNode;
}) {
  const [view, setView] = useState<"live" | "history" | "gpu">("live");
  const gpu = report.gpu;
  const url = safeAppUrl(report.url, "org.mediahub.plex-gpu-transcoder");
  const fresh = report.available && !report.observationHealth;
  const jobs = fresh ? gpu?.activeJobs : null;
  const stopped = fresh && report.state === "stopped";
  const encoding = !stopped && (jobs ?? 0) > 0;
  const activity = stopped
    ? t("Stopped")
    : encoding
      ? t("Encoding now")
      : jobs === 0 && gpu?.linked
        ? t("Ready · no active jobs")
        : t("Status unavailable");
  const checked =
    fresh && report.observedAt
      ? new Date(report.observedAt * 1000).toLocaleTimeString()
      : null;
  const value = (number: number | null | undefined, suffix = "") =>
    number == null ? t("Not observed") : `${Math.round(number)}${suffix}`;
  const overview = [
    ["Active playbacks", fresh ? gpu?.activePlaybacks : null, ""],
    ["Active GPU jobs", jobs, ""],
    ["GPU encoder", fresh ? gpu?.encoderPercent : null, " %"],
  ] as const;
  return (
    <div className="stack plex-gpu-view">
      <header className="runtime-summary">
        <div>
          <h1>Plex GPU Transcoder</h1>
          <p>
            {checked
              ? t("Updated at {time}", { time: checked })
              : t("Status unavailable")}
          </p>
        </div>
        <div
          className={`runtime-health ${encoding ? "healthy" : ""}`}
          role="status"
        >
          {activity}
        </div>
      </header>
      <dl className="plex-gpu-overview">
        {overview.map(([label, number, suffix]) => (
          <div key={label}>
            <dt>{t(label)}</dt>
            <dd>{number == null ? "—" : value(number, suffix)}</dd>
          </div>
        ))}
      </dl>
      <nav className="plex-gpu-navigation" aria-label={t("Transcoder views")}>
        {(
          [
            ["live", "Now playing", Activity],
            ["history", "History", History],
            ["gpu", "GPU", Cpu],
          ] as const
        ).map(([key, label, Icon]) => (
          <button
            key={key}
            type="button"
            aria-pressed={view === key}
            onClick={() => setView(key)}
          >
            <Icon size={16} aria-hidden="true" />
            {t(label)}
          </button>
        ))}
      </nav>
      {view === "live" && (
        <PlexGPUSessions
          playbacks={gpu?.playbacks}
          count={gpu?.activePlaybacks}
          available={gpu?.playbackAvailable}
          fresh={fresh}
        />
      )}
      {view === "history" && (
        <PlexGPUHistory
          playbacks={gpu?.playbacks}
          jobs={gpu?.jobs}
          fresh={fresh}
        />
      )}
      <div hidden={view !== "gpu"}>
        <div className="stack">
          <div className="runtime-panels">
            <Panel title={t("NVIDIA GPU")}>
              <dl>
                <div className="runtime-row">
                  <dt>{t("Graphics card")}</dt>
                  <dd>{gpu?.name || t("Not observed")}</dd>
                </div>
                <div className="runtime-row">
                  <dt>{t("GPU encoder")}</dt>
                  <dd>{value(fresh ? gpu?.encoderPercent : null, " %")}</dd>
                </div>
                <div className="runtime-row">
                  <dt>{t("Graphics memory")}</dt>
                  <dd>
                    {value(fresh ? gpu?.memoryUsedMiB : null)} /{" "}
                    {value(fresh ? gpu?.memoryTotalMiB : null, " MiB")}
                  </dd>
                </div>
                <div className="runtime-row">
                  <dt>{t("Temperature")}</dt>
                  <dd>{value(fresh ? gpu?.temperature : null, " °C")}</dd>
                </div>
              </dl>
              <p className="muted">
                {t("GPU usage includes other applications sharing the card.")}
              </p>
            </Panel>
            <Panel title={t("Plex connection")}>
              <dl>
                <div className="runtime-row">
                  <dt>{t("Connection")}</dt>
                  <dd>
                    {gpu?.linked
                      ? t("Connected")
                      : t("Waiting for Plex connection")}
                  </dd>
                </div>
                <div className="runtime-row">
                  <dt>{t("Transcode jobs")}</dt>
                  <dd>{jobs ?? t("Not observed")}</dd>
                </div>
              </dl>
              {fresh && gpu?.bufferSeconds != null && (
                <p>
                  {t("Starting buffer: {seconds} sec.", {
                    seconds: Math.round(gpu.bufferSeconds),
                  })}
                </p>
              )}
              {url && (
                <a href={url} target="_blank" rel="noopener noreferrer">
                  {t("Open GPU dashboard on local network")} ↗
                </a>
              )}
              <p className="muted">
                {t(
                  gpu?.hdrToneMapping
                    ? "HDR10 and HLG use GPU tone mapping to SDR. Unsupported jobs use Plex's original transcoder."
                    : "HDR GPU conversion is unavailable. HDR jobs use Plex's original transcoder.",
                )}
              </p>
            </Panel>
          </div>
          {extraCards}
        </div>
      </div>
    </div>
  );
}
