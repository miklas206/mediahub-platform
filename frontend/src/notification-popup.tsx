import { Children, createContext, isValidElement, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { t } from "./i18n";
import { notificationSeason, NotificationSeasonArt, nextNotificationAnimal, type NotificationAnimal, type NotificationSeason } from "./notification-season";
import "./notification-popup.css";

type Tone = "danger" | "warning" | "info" | "success";
type Notification = { id: string; message: ReactNode; tone: Tone };
const NotificationContext = createContext<(notification: Notification) => void>(() => {});

function messageText(message: ReactNode): string {
  return Children.toArray(message).map((child) =>
    isValidElement<{ children?: ReactNode }>(child) ? messageText(child.props.children) : String(child),
  ).join("");
}

function Popup({ notification, dismiss }: { notification: Notification; dismiss: (id: string) => void }) {
  const [paused, setPaused] = useState(false);
  const [closing, setClosing] = useState(false);
  const remaining = useRef(notification.tone === "danger" ? 9000 : 6000);
  useEffect(() => {
    if (closing) {
      const timer = window.setTimeout(() => dismiss(notification.id), window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 240);
      return () => window.clearTimeout(timer);
    }
    if (paused) return;
    const started = Date.now();
    const timer = window.setTimeout(() => setClosing(true), remaining.current);
    return () => {
      window.clearTimeout(timer);
      remaining.current = Math.max(0, remaining.current - (Date.now() - started));
    };
  }, [paused, closing, dismiss, notification.id]);
  const Icon = notification.tone === "success" ? CheckCircle2 : notification.tone === "info" ? Info : AlertTriangle;
  return (
    <div className={`notification-popup ${notification.tone}${closing ? " is-closing" : ""}`} data-paused={paused} role={notification.tone === "danger" ? "alert" : "status"}
      onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setPaused(false); }}>
      <span className="notification-code" aria-hidden="true">
        {Array.from({ length: 8 }, (_, index) => <span key={index} style={{ left: `${index * 13}%`, animationDelay: `${index * -0.7}s` }}>{index % 2 ? "10:01\n0011\n01:10\n1100\n1010" : "0101\n11:00\n1001\n00:11\n0110"}</span>)}
      </span>
      <Icon size={19} aria-hidden="true" />
      <div className="notification-message">{notification.message}</div>
      <button type="button" disabled={closing} aria-label={t("Dismiss notification")} title={t("Dismiss notification")} onClick={() => setClosing(true)}><X size={16} /></button>
      <span className="notification-lifetime" aria-hidden="true" style={{ animationDuration: notification.tone === "danger" ? "9s" : "6s" }} />
    </div>
  );
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [duckRun, setDuckRun] = useState(0);
  const [artwork, setArtwork] = useState<{ season: NotificationSeason; animal: NotificationAnimal }>({ season: notificationSeason(new Date()), animal: "duck" });
  const previousAnimal = useRef<NotificationAnimal | undefined>(undefined);
  useEffect(() => {
    if (!duckRun) return;
    const timer = window.setTimeout(() => setDuckRun(0), 10000);
    return () => window.clearTimeout(timer);
  }, [duckRun]);
  const push = useCallback((notification: Notification) => {
    setNotifications((current) => [notification, ...current.filter((item) => item.id !== notification.id)].slice(0, 4));
  }, []);
  const dismiss = useCallback((id: string) => {
    setNotifications((current) => current.filter((item) => item.id !== id));
    const animal = nextNotificationAnimal(previousAnimal.current);
    previousAnimal.current = animal;
    setArtwork({ season: notificationSeason(new Date()), animal });
    setDuckRun((current) => current + 1);
  }, []);
  return (
    <NotificationContext.Provider value={push}>
      {children}
      <div className="notification-popups" aria-label={t("Notifications")}>
        {notifications.map((notification) => <Popup key={notification.id} notification={notification} dismiss={dismiss} />)}
      </div>
      {duckRun > 0 && <div key={duckRun} className="notification-duck" aria-hidden="true" data-season={artwork.season} data-animal={artwork.animal}><span><NotificationSeasonArt season={artwork.season} animal={artwork.animal} /></span></div>}
    </NotificationContext.Provider>
  );
}

export function NotificationPopup({ children, tone = "info" }: { children: ReactNode; tone?: Tone }) {
  const push = useContext(NotificationContext);
  const id = useId();
  const text = messageText(children);
  const content = useRef(children);
  content.current = children;
  useEffect(() => {
    if (text.trim()) push({ id: `${id}:${text}:${tone}`, message: content.current, tone });
  }, [id, text, tone, push]);
  return null;
}