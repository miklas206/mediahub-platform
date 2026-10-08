import { useCallback, useEffect, useId, useRef, useState } from "react";
import { ArrowUpRight, Search, SearchX, X } from "lucide-react";
import { Link } from "react-router-dom";
import { t, useLanguage } from "./i18n";
import "./workspace-search.css";

type Destination = { label: string; path: string };

function searchText(value: string) {
  return value
    .normalize("NFKD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase();
}

export function WorkspaceSearch({
  destinations,
}: {
  destinations: Destination[];
}) {
  useLanguage();
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const inputId = useId();
  const [query, setQuery] = useState("");
  const visible = destinations.filter((destination) =>
    searchText(t(destination.label)).includes(searchText(query.trim())),
  );

  const openSearch = useCallback(() => {
    setQuery("");
    dialog.current?.showModal();
    input.current?.focus();
  }, []);

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (event.repeat) return;
        if (dialog.current?.open) dialog.current.close();
        else openSearch();
      }
    }
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, [openSearch]);

  return (
    <>
      <button
        className="workspace-search-trigger"
        type="button"
        onClick={openSearch}
        aria-label={t("Search pages and services")}
        aria-keyshortcuts="Control+K Meta+K"
      >
        <Search size={17} strokeWidth={1.75} aria-hidden="true" />
        <span>{t("Search pages and services…")}</span>
        <kbd>Ctrl K</kbd>
      </button>
      <dialog
        ref={dialog}
        className="workspace-search-dialog"
        aria-labelledby={titleId}
        onClick={(event) => {
          if (event.target !== event.currentTarget) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX < bounds.left ||
            event.clientX > bounds.right ||
            event.clientY < bounds.top ||
            event.clientY > bounds.bottom
          ) {
            dialog.current?.close();
          }
        }}
      >
        <header className="workspace-search-heading">
          <h2 id={titleId}>{t("Quick navigation")}</h2>
          <button
            type="button"
            className="topbar-action"
            aria-label={t("Close")}
            onClick={() => dialog.current?.close()}
          >
            <X size={18} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </header>
        <div className="workspace-search-field">
          <Search size={19} strokeWidth={1.75} aria-hidden="true" />
          <label className="workspace-search-label" htmlFor={inputId}>
            {t("Search pages and services")}
          </label>
          <input
            autoFocus
            ref={input}
            id={inputId}
            type="search"
            autoComplete="off"
            placeholder={t("Search pages and services…")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                dialog.current
                  ?.querySelector<HTMLAnchorElement>(
                    ".workspace-search-results a",
                  )
                  ?.focus();
              }
              if (event.key === "Enter") {
                event.preventDefault();
                dialog.current
                  ?.querySelector<HTMLAnchorElement>(
                    ".workspace-search-results a",
                  )
                  ?.click();
              }
            }}
          />
        </div>
        <p className="workspace-search-count" role="status">
          {t("{count} results", { count: visible.length })}
        </p>
        {visible.length > 0 ? (
          <ul
            className="workspace-search-results"
            aria-label={t("Navigation results")}
          >
            {visible.map((destination) => (
              <li key={destination.path}>
                <Link
                  to={destination.path}
                  onClick={() => dialog.current?.close()}
                >
                  <span>{t(destination.label)}</span>
                  <ArrowUpRight
                    size={17}
                    strokeWidth={1.75}
                    aria-hidden="true"
                  />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <div className="workspace-search-empty">
            <SearchX size={25} strokeWidth={1.75} aria-hidden="true" />
            <strong>{t("No matching pages")}</strong>
            <p>{t("Try a different page or service name.")}</p>
          </div>
        )}
        <footer className="workspace-search-footer">
          <span>{t("Use Tab to choose a page")}</span>
          <span>
            <kbd>Esc</kbd> {t("Close")}
          </span>
        </footer>
      </dialog>
    </>
  );
}
