import { t } from "./i18n";
import { useEffect, useState } from "react";
import { Clock3 } from "lucide-react";

const clockFormat = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

export function SidebarClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const refresh = () => setNow(new Date());
    const timer = window.setInterval(refresh, 1000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);

  return (
    <div className="sidebar-clock" title={t("Local time")}>
      <Clock3 size={15} aria-hidden="true" />
      <time dateTime={now.toISOString()} aria-label={t("Local time")}>
        {clockFormat.format(now)}
      </time>
    </div>
  );
}
