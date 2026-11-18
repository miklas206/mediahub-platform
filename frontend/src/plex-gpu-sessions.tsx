import { useState } from "react";
import { t } from "./i18n";
import { Panel } from "./phase2";

export type PlexGPUSession = {
  id: string;
  media: string;
  user?: string | null;
  player?: string | null;
  status: string;
  playbackMode?: string | null;
  encoder?: string | null;
  started?: number | null;
  position?: number | null;
  duration?: number | null;
  segments?: number | null;
  speed?: string | null;
  bufferSeconds?: number | null;
  bufferTargetSeconds?: number | null;
  live?: boolean;
  usingGpu?: boolean | null;
  paused?: boolean;
  throttled?: boolean;
};

const modes: Record<string, string> = {
  direct_play: "Direct Play",
  direct_stream: "Direct Stream",
  transcode: "Transcoding",
  fallback: "Plex fallback",
  unknown: "Not observed",
};

const states: Record<string, string> = {
  playing: "Playing",
  paused: "Paused",
  buffering: "Buffering",
  starting: "Starting",
  encoding: "Encoding now",
  complete: "Completed",
  ended: "Completed",
  stopped: "Stopped",
  interrupted: "Interrupted",
  failed: "Failed",
  passthrough: "Direct Stream",
  fallback: "Plex fallback",
};

function playbackTime(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(seconds / 60);
  const rest = String(seconds % 60).padStart(2, "0");
  return minutes < 60
    ? `${minutes}:${rest}`
    : `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}:${rest}`;
}

function SessionDetails({ row }: { row: PlexGPUSession }) {
  const state = row.paused
    ? "Paused"
    : row.throttled
      ? "Buffer ready"
      : Object.hasOwn(states, row.status)
        ? states[row.status]
        : "Not observed";
  const details = [
    row.player,
    row.user,
    row.encoder,
    row.usingGpu && !row.encoder && t("GPU"),
    row.speed && t("{speed} encoding speed", { speed: row.speed }),
    row.segments != null && t("{count} segments", { count: row.segments }),
  ].filter(Boolean);
  return (
    <article className="plex-gpu-session">
      <strong>{row.media || t("Plex playback")}</strong>
      <div>
        {[
          row.playbackMode &&
            t(
              Object.hasOwn(modes, row.playbackMode)
                ? modes[row.playbackMode]
                : "Not observed",
            ),
          t(state),
        ]
          .filter(Boolean)
          .join(" · ")}
      </div>
      {details.length > 0 && <p className="muted">{details.join(" · ")}</p>}
      {row.duration != null && row.duration > 0 && row.position != null && (
        <div className="plex-gpu-progress">
          <progress
            aria-label={t("Playback progress")}
            value={Math.min(row.position, row.duration)}
            max={row.duration}
          />
          <small className="muted">
            {playbackTime(Math.min(row.position, row.duration))} /{" "}
            {playbackTime(row.duration)}
          </small>
        </div>
      )}
      {row.bufferSeconds != null && (
        <p>
          {t("Buffer: {seconds} sec.", {
            seconds: Math.round(row.bufferSeconds),
          })}
          {row.bufferTargetSeconds != null && (
            <>
              {" "}
              ·{" "}
              {t("Target: {seconds} sec.", {
                seconds: Math.round(row.bufferTargetSeconds),
              })}
            </>
          )}
        </p>
      )}
      {row.started != null && (
        <small className="muted">
          {new Date(row.started * 1000).toLocaleString()}
        </small>
      )}
    </article>
  );
}

export function PlexGPUSessions({
  playbacks = [],
  count,
  available,
  hasObservation,
}: {
  playbacks?: PlexGPUSession[];
  count?: number | null;
  available?: boolean | null;
  hasObservation: boolean;
}) {
  const active = playbacks.filter((row) => row.live);
  return (
    <Panel title="Live Plex playbacks">
      {!hasObservation ? (
        <p>{t("Status unavailable")}</p>
      ) : available !== true ? (
        <p>{t("Plex playback details are unavailable")}</p>
      ) : active.length ? (
        active.map((row) => <SessionDetails key={row.id} row={row} />)
      ) : (
        <p>
          {t(
            count === 0
              ? "No active playbacks"
              : "No playback details available",
          )}
        </p>
      )}
    </Panel>
  );
}

export function PlexGPUHistory({
  playbacks = [],
  jobs = [],
  hasObservation,
}: {
  playbacks?: PlexGPUSession[];
  jobs?: PlexGPUSession[];
  hasObservation: boolean;
}) {
  const [showJobs, setShowJobs] = useState(false);
  const [limit, setLimit] = useState(10);
  const rows = (showJobs ? jobs : playbacks.filter((row) => !row.live))
    .slice()
    .sort((first, second) => (second.started ?? 0) - (first.started ?? 0));
  return (
    <Panel title="History">
      {!hasObservation ? (
        <p>{t("Status unavailable")}</p>
      ) : (
        <div className="stack">
          <div
            className="plex-gpu-navigation"
            role="group"
            aria-label={t("History")}
          >
            <button
              type="button"
              aria-pressed={!showJobs}
              onClick={() => {
                setShowJobs(false);
                setLimit(10);
              }}
            >
              {t("Recent playbacks")}
            </button>
            <button
              type="button"
              aria-pressed={showJobs}
              onClick={() => {
                setShowJobs(true);
                setLimit(10);
              }}
            >
              {t("Transcode jobs")}
            </button>
          </div>
          {rows.length ? (
            rows
              .slice(0, limit)
              .map((row) => <SessionDetails key={row.id} row={row} />)
          ) : (
            <p>{t("No history available")}</p>
          )}
          {rows.length > limit && (
            <button
              type="button"
              onClick={() => setLimit((current) => current + 10)}
            >
              {t("Show more")}
            </button>
          )}
        </div>
      )}
    </Panel>
  );
}
