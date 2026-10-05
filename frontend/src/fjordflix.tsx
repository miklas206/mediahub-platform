import { useState } from "react";
import { Film } from "lucide-react";
import { Panel } from "./phase2";
import "./fjordflix.css";

export type FjordFlixItem = {
  id?: string;
  title?: string;
  poster_id?: string;
  overview?: string;
  release_date?: string;
  genres?: string[];
  rating?: number;
  media_type?: string;
  series_title?: string;
  season?: number;
  episode?: number;
};
export type FjordFlixStream = FjordFlixItem & {
  movie_id?: string;
  user?: string;
  client?: string;
  state?: string;
  mode?: string;
  position?: number;
  duration?: number;
  height?: number;
  mbps?: number;
  video?: string;
  audio?: string;
  subtitle?: string;
  encoder?: string;
};
export type FjordFlixData = {
  ok: boolean;
  stale?: boolean;
  error?: string;
  status?: number;
  generated_at?: string;
  library_count?: number;
  items?: FjordFlixItem[];
  streams?: FjordFlixStream[];
};

function Poster({
  integration,
  item,
}: {
  integration: string;
  item: FjordFlixItem;
}) {
  const src =
    item.poster_id && /^[A-Za-z0-9_-]{1,128}$/.test(item.poster_id)
      ? `/api/v1/integrations/${encodeURIComponent(integration)}/fjordflix/posters/${encodeURIComponent(item.poster_id)}`
      : undefined;
  const [failed, setFailed] = useState<string>();
  return (
    <div className="fjordflix-poster">
      {src && failed !== src ? (
        <img
          src={src}
          alt={item.title || "Poster"}
          loading="lazy"
          onError={() => setFailed(src)}
        />
      ) : (
        <span role="img" aria-label="Poster unavailable">
          <Film size={32} />
        </span>
      )}
    </div>
  );
}

const seconds = (value?: number) =>
  value === undefined
    ? "—"
    : `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, "0")}`;

export function FjordFlix({
  integration,
  data,
}: {
  integration: string;
  data?: FjordFlixData | null;
}) {
  if (!data) return null;
  return (
    <Panel title="FjordFlix">
      <div className="fjordflix-content">
        {data.stale && (
          <p role="status" className="fjordflix-warning">
            Showing last good FjordFlix data · stale
          </p>
        )}
        {data.error && <p role="status">{data.error}</p>}
        {data.ok && (
          <>
            <div className="fjordflix-heading">
              <h3>Recently added · last 10</h3>
              <span className="muted">
                {data.library_count ?? "—"} titles in library
              </span>
            </div>
            {data.generated_at && (
              <small className="muted">Updated {data.generated_at}</small>
            )}
            {!data.items?.length ? (
              <p>No titles in the library.</p>
            ) : (
              <div className="fjordflix-gallery">
                {data.items.slice(0, 10).map((item, index) => (
                  <article className="fjordflix-title" key={item.id ?? index}>
                    <Poster integration={integration} item={item} />
                    <h4>{item.title || "Untitled"}</h4>
                    <small className="muted">
                      {[
                        item.release_date?.slice(0, 4),
                        item.media_type,
                        item.rating !== undefined
                          ? `★ ${item.rating}`
                          : undefined,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </small>
                    {item.series_title && (
                      <p>
                        {item.series_title}
                        {item.season !== undefined && ` · S${item.season}`}
                        {item.episode !== undefined && ` E${item.episode}`}
                      </p>
                    )}
                    {!!item.genres?.length && (
                      <small>{item.genres.join(" · ")}</small>
                    )}
                    {item.overview && (
                      <details>
                        <summary>Overview</summary>
                        <p>{item.overview}</p>
                      </details>
                    )}
                  </article>
                ))}
              </div>
            )}
            <h3>
              Current streams{" "}
              <span className="muted">({data.streams?.length ?? 0})</span>
            </h3>
            {!data.streams?.length ? (
              <p>No active streams.</p>
            ) : (
              <div className="fjordflix-streams">
                {data.streams.map((stream, index) => (
                  <article
                    className="fjordflix-stream"
                    key={stream.id ?? index}
                  >
                    <Poster integration={integration} item={stream} />
                    <div>
                      <h4>{stream.title || "Untitled"}</h4>
                      <p>
                        {[stream.user, stream.client, stream.state, stream.mode]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                      <p className="muted">
                        {seconds(stream.position)} / {seconds(stream.duration)}
                        {stream.height !== undefined && ` · ${stream.height}p`}
                        {stream.mbps !== undefined &&
                          ` · ${stream.mbps} Mbit/s`}
                      </p>
                      {stream.duration !== undefined && stream.duration > 0 && (
                        <progress
                          aria-label={`${stream.title || "Stream"} playback progress`}
                          max={stream.duration}
                          value={Math.min(
                            stream.position ?? 0,
                            stream.duration,
                          )}
                        />
                      )}
                      <small>
                        {[
                          stream.video,
                          stream.audio,
                          stream.subtitle,
                          stream.encoder,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </small>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}
