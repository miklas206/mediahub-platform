import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, ChevronRight, Film } from "lucide-react";
import { Link } from "react-router-dom";
import type { Integration } from "./integrations";
import { fjordHubAppLink } from "./fjordhub-app-link";
import { FjordFlixPoster } from "./fjordflix";
import { t } from "./i18n";
import { FjordHubIcon } from "./fjordhub-updates";

export function FjordFlixDashboardCard({
  row,
}: {
  row: Integration;
  title?: string;
}) {
  const data = row.snapshot.fjordflix;
  const rail = useRef<HTMLDivElement>(null);
  const [overflow, setOverflow] = useState(false);
  const items = data?.ok ? (data.items || []).slice(0, 10) : [];
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
  if (!row.enabled || !row.tokenConfigured || !data) return null;
  const app = row.snapshot.apps?.find((app) => app.id === "fjordflix");
  const link = app
    ? fjordHubAppLink(row.baseUrl, app, row.appLaunchOverrides, row.allowHttp)
    : null;
  const stale = !!data.stale;
  return (
    <article
      data-layout-title={`FjordFlix · ${row.name}`}
      className="service-card service-tile plex-service-tile fjordflix-service-tile"
      aria-label={`FjordFlix · ${row.name}`}
    >
      <div className="service-tile-title">
        <FjordHubIcon row={row} appId="fjordflix" size={32} />
        <h3>FjordFlix</h3>
        <span
          className={`badge ${stale ? "degraded" : data.ok ? "healthy" : "unknown"}`}
        >
          {stale ? t("Stale") : data.ok ? t("Connected") : t("Unavailable")}
        </span>
      </div>
      <small className="muted">{row.name}</small>
      <dl className="service-facts">
        <div>
          <dd>{data.ok ? (data.streams?.length ?? 0) : "—"}</dd>
          <dt>{t("Active streams")}</dt>
        </div>
        <div>
          <dd>{data.ok ? (data.library_count ?? "—") : "—"}</dd>
          <dt>{t("Titles in library")}</dt>
        </div>
      </dl>
      {stale && (
        <p role="status" className="fjordflix-warning">
          Showing last good FjordFlix data · stale
        </p>
      )}
      {data.error && <p role="status">{data.error}</p>}
      <div className="plex-recent-media">
        {items.length ? (
          <>
            <div
              className="plex-posters"
              ref={rail}
              aria-label="FjordFlix recently added · last 10"
            >
              {items.map((item, index) => (
                <Link
                  className="plex-poster"
                  to={`/integrations/${encodeURIComponent(row.id)}`}
                  key={item.id ?? index}
                  title={item.title || "Untitled"}
                >
                  <FjordFlixPoster integration={row.id} item={item} />
                </Link>
              ))}
            </div>
            {overflow && (
              <button
                className="plex-posters-next"
                type="button"
                aria-label={t("Show more covers")}
                onClick={() => {
                  const element = rail.current;
                  if (element)
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
              {data.ok
                ? "No titles in the library."
                : "FjordFlix data is unavailable."}
            </span>
          </div>
        )}
      </div>
      {link ? (
        <a
          className="service-open"
          href={link.href}
          target="_blank"
          rel="noopener noreferrer"
        >
          {link.management
            ? "Manage FjordFlix in FjordHub (app address unavailable)"
            : "Open FjordFlix"}
          <ArrowUpRight size={13} />
        </a>
      ) : (
        <Link
          className="service-open"
          to={`/integrations/${encodeURIComponent(row.id)}`}
        >
          View FjordFlix integration
          <ArrowUpRight size={13} />
        </Link>
      )}
    </article>
  );
}
