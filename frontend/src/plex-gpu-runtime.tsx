import type { ReactNode } from "react";
import type { Runtime } from "./runtime";
import { Panel } from "./phase2";
import { t } from "./i18n";
import { safeAppUrl } from "./app-uptime";

export function PlexGPUPanel({ report, extraCards }: {
  report: Runtime; appId?: string; extraCards?: ReactNode;
}) {
  const gpu = report.gpu;
  const url = safeAppUrl(report.url, "org.mediahub.plex-gpu-transcoder");
  const value = (number: number | null | undefined, suffix = "") =>
    number == null ? t("Not observed") : `${Math.round(number)}${suffix}`;
  return (
    <div className="stack">
      <header className="runtime-summary">
        <div>
          <p className="eyebrow">MEDIAHUB · PLEX GPU</p>
          <h1>Plex GPU Transcoder</h1>
          <p>{t("A separate GPU container connected to your existing Plex.")}</p>
        </div>
        {url && <a className="button" href={url} target="_blank" rel="noopener noreferrer">{t("Open GPU dashboard")} ↗</a>}
      </header>
      <div className="runtime-panels">
        <Panel title={t("NVIDIA GPU")}>
          <dl>
            <div className="runtime-row"><dt>{t("Graphics card")}</dt><dd>{gpu?.name || t("Not observed")}</dd></div>
            <div className="runtime-row"><dt>{t("GPU encoder")}</dt><dd>{value(gpu?.encoderPercent, " %")}</dd></div>
            <div className="runtime-row"><dt>{t("Graphics memory")}</dt><dd>{value(gpu?.memoryUsedMiB)} / {value(gpu?.memoryTotalMiB, " MiB")}</dd></div>
            <div className="runtime-row"><dt>{t("Temperature")}</dt><dd>{value(gpu?.temperature, " °C")}</dd></div>
          </dl>
          <p className="muted">{t("GPU usage includes other applications sharing the card.")}</p>
        </Panel>
        <Panel title={t("Plex connection")}>
          <dl>
            <div className="runtime-row"><dt>{t("Connection")}</dt><dd>{gpu?.linked ? t("Connected") : t("Waiting for Plex connection")}</dd></div>
            <div className="runtime-row"><dt>{t("Transcode jobs")}</dt><dd>{gpu?.activeJobs ?? t("Not observed")}</dd></div>
          </dl>
          <p>{t("Direct Play does not create a GPU job.")}</p>
          <p className="muted">{t("HDR and unsupported jobs use Plex's original transcoder.")}</p>
        </Panel>
      </div>
      {extraCards}
    </div>
  );
}
