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
        <progress
          aria-label={t("Playback progress")}
          value={Math.min(row.position, row.duration)}
          max={row.duration}
        />
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
  jobs = [],
  count,
  available,
  fresh,
  buffer,
}: {
  playbacks?: PlexGPUSession[];
  jobs?: PlexGPUSession[];
  count?: number | null;
  available?: boolean | null;
  fresh: boolean;
  buffer?: number | null;
}) {
  const active = playbacks.filter((row) => row.live);
  const recent = playbacks.filter((row) => !row.live);
  const render = (rows: PlexGPUSession[]) =>
    rows.map((row) => <SessionDetails key={row.id} row={row} />);

  return (
    <Panel title={t("Plex playbacks")}>
      {!fresh ? (
        <p>{t("Status unavailable")}</p>
      ) : (
        <div className="stack">
          {available === true ? (
            <>
              {count != null && (
                <strong>{t("Active playbacks: {count}", { count })}</strong>
              )}
              {!active.length && (
                <p>
                  {t(
                    count === 0
                      ? "No active playbacks"
                      : "No playback details available",
                  )}
                </p>
              )}
              {render(active)}
            </>
          ) : (
            <p>{t("Plex playback details are unavailable")}</p>
          )}
          {buffer != null && (
            <p className="muted">
              {t("Starting buffer: {seconds} sec.", {
                seconds: Math.round(buffer),
              })}
            </p>
          )}
          {!!recent.length && (
            <details>
              <summary>
                {t("Recent playbacks")} · {recent.length}
              </summary>
              {render(recent)}
            </details>
          )}
          {!!jobs.length && (
            <details>
              <summary>
                {t("Transcode jobs")} · {jobs.length}
              </summary>
              {render(jobs)}
            </details>
          )}
        </div>
      )}
    </Panel>
  );
}
