import { translateText, t } from "./i18n";

import { useEffect, useState } from "react";
import { api } from "./api";
import { ErrorBox, Panel } from "./phase2";

type Settings = { intervalSeconds: number };
const path = "/seedbox/rss/feeds/settings";

export function SeedboxRSSSettings() {
  const [saved, setSaved] = useState<number | null>(null);
  const [minutes, setMinutes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void api<Settings>(path, "GET", undefined, controller.signal)
      .then((settings) => {
        if (controller.signal.aborted) return;
        setSaved(settings.intervalSeconds);
        setMinutes(String(settings.intervalSeconds / 60));
      })
      .catch((e: Error) => {
        if (!controller.signal.aborted) setError(e.message);
      });
    return () => controller.abort();
  }, []);
  const seconds = Number(minutes) * 60;
  const valid =
    minutes !== "" &&
    Number.isInteger(Number(minutes)) &&
    seconds >= 60 &&
    seconds <= 86400;
  return (
    <Panel title={t("RSS feed settings")}>
      <ErrorBox error={error} />
      {saved === null && !error && (
        <p role="status">{t("Loading feed settings…")}</p>
      )}
      <p className="muted">
        {t(
          "Choose how often MediaHub checks automatic feeds for new files, even when this page is closed. This interval applies to all automatic feeds. Manual feeds are checked using Check feed now.",
        )}
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!valid || busy || saved === null) return;
          setBusy(true);
          setError("");
          setNotice("");
          void api<Settings>(path, "PUT", { intervalSeconds: seconds })
            .then((settings) => {
              setSaved(settings.intervalSeconds);
              setMinutes(String(settings.intervalSeconds / 60));
              setNotice(t("Feed settings saved. The new interval is active."));
            })
            .catch((e: Error) => setError(e.message))
            .finally(() => setBusy(false));
        }}
      >
        <label>
          {t("Check for new files every (minutes)")}
          <input
            type="number"
            min={1}
            max={1440}
            step={1}
            required
            value={minutes}
            disabled={busy || saved === null}
            onChange={(event) => {
              setMinutes(event.target.value);
              setNotice("");
            }}
          />
        </label>
        <p className="muted">
          {t(
            "Between 1 minute and 24 hours. Default: 5 minutes. Checks are scheduled from each feed's last check and may start up to 15 seconds later.",
          )}
        </p>
        <button
          className="primary"
          disabled={busy || saved === null || !valid || seconds === saved}
        >
          {busy ? t("Saving…") : t("Save feed settings")}
        </button>
        {notice && <p role="status">{translateText(notice)}</p>}
      </form>
    </Panel>
  );
}
