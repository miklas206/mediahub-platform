import type { ReactNode } from "react";
import type { Runtime } from "./runtime";
import { PlexGPUSessions } from "./plex-gpu-sessions";
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
  return (
    <div className="stack">
      <header className="runtime-summary">
        <div>
          <p className="eyebrow">MEDIAHUB · PLEX GPU</p>
          <h1>Plex GPU Transcoder</h1>
          <p>
            {t("Status refreshes every 10 seconds while this page is open.")}
            {checked && <> · {checked}</>}
          </p>
        </div>
        <div
          className={`runtime-health ${encoding ? "healthy" : ""}`}
          role="status"
        >
          {activity}
        </div>
      </header>
      <PlexGPUSessions
        playbacks={gpu?.playbacks}
        jobs={gpu?.jobs}
        count={gpu?.activePlaybacks}
        available={gpu?.playbackAvailable}
        fresh={fresh}
        buffer={gpu?.bufferSeconds}
      />
      <div className="runtime-panels">
        <Panel title={t("NVIDIA GPU")}>
          <dl>
            <div className="runtime-row">
              <dt>{t("Graphics card")}</dt>
              <dd>{gpu?.name || t("Not observed")}</dd>
            </div>
            <div className="runtime-row">
              <dt>{t("GPU encoder")}</dt>
              <dd>{value(gpu?.encoderPercent, " %")}</dd>
            </div>
            <div className="runtime-row">
              <dt>{t("Graphics memory")}</dt>
              <dd>
                {value(gpu?.memoryUsedMiB)} /{" "}
                {value(gpu?.memoryTotalMiB, " MiB")}
              </dd>
            </div>
            <div className="runtime-row">
              <dt>{t("Temperature")}</dt>
              <dd>{value(gpu?.temperature, " °C")}</dd>
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
          <p>{t("Direct Play does not create a GPU job.")}</p>
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
  );
}
