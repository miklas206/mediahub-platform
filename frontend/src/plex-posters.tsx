import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, Film } from "lucide-react";
import { useServiceSnapshot } from "./use-service-snapshot";
import { t } from "./i18n";

type Media = {
  id: string;
  title: string;
  type: string;
  year: number | null;
  thumbnailUrl: string | null;
};
type RecentMedia = { supported: boolean; items: Media[] };

function Poster({ item, appId }: { item: Media; appId: string }) {
  const [failed, setFailed] = useState(false);
  const expected = `/api/v1/apps/${encodeURIComponent(appId)}/plex/artwork/`;
  const thumbnail = item.thumbnailUrl?.startsWith(expected)
    ? item.thumbnailUrl
    : null;
  return (
    <Link
      className="plex-poster"
      to={`/apps/${appId}`}
      title={`${item.title}${item.year ? ` · ${item.year}` : ""}`}
    >
      {thumbnail && !failed ? (
        <img
          src={thumbnail}
          alt={item.title}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="plex-poster-fallback">
          <Film size={20} />
          <small>{item.title}</small>
        </span>
      )}
    </Link>
  );
}

export function PlexPosters({ appId }: { appId: string }) {
  const { data, error, stale, refreshing } = useServiceSnapshot<RecentMedia>(
    "recent",
    appId,
    60000,
  );
  const failed = !!error;
  const [overflow, setOverflow] = useState(false);
  const rail = useRef<HTMLDivElement>(null);
  const items = data?.items || [];
  useEffect(() => {
    const element = rail.current;
    if (!element) return;
    const update = () =>
      setOverflow(element.scrollWidth > element.clientWidth + 2);
    const observer = new ResizeObserver(update);
    observer.observe(element);
    update();
    return () => observer.disconnect();
  }, [items.length]);
  return (
    <div className="plex-recent-media">
      {data && stale && (
        <small className="plex-posters-observation" role="status">
          {t(
            refreshing
              ? "Stale observation - refreshing"
              : "Stale observation - temporarily unavailable",
          )}
        </small>
      )}
      {items.length ? (
        <>
          <div
            className="plex-posters"
            ref={rail}
            aria-label={t("Recently added media")}
          >
            {items.slice(0, 8).map((item) => (
              <Poster key={item.id} item={item} appId={appId} />
            ))}
          </div>
          {overflow && (
            <button
              className="plex-posters-next"
              type="button"
              aria-label={t("Show more covers")}
              onClick={() => {
                const element = rail.current;
                if (!element) return;
                element.scrollTo({
                  left:
                    element.scrollLeft + element.clientWidth >=
                    element.scrollWidth - 2
                      ? 0
                      : element.scrollLeft + element.clientWidth,
                  behavior: "smooth",
                });
              }}
            >
              <ChevronRight size={15} />
            </button>
          )}
        </>
      ) : (
        <div className="plex-covers-empty">
          <Film size={24} />
          <span>
            {t(
              failed
                ? "Covers are temporarily unavailable"
                : data?.supported === false
                  ? "Update the Plex Agent to show covers"
                  : data
                    ? "No recent media"
                    : "Loading covers…",
            )}
          </span>
        </div>
      )}
    </div>
  );
}
