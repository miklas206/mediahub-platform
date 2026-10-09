import { Children, createContext, isValidElement, useCallback, useContext, useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { t } from "./i18n";
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
      const timer = window.setTimeout(() => dismiss(notification.id), window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 480);
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
    <div className={`notification-popup ${notification.tone}${closing ? " is-popping" : ""}`} role={notification.tone === "danger" ? "alert" : "status"}
      onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setPaused(false); }}>
      <Icon size={19} aria-hidden="true" />
      <div>{notification.message}</div>
      <button type="button" disabled={closing} aria-label={t("Dismiss notification")} title={t("Dismiss notification")} onClick={() => setClosing(true)}><X size={16} /></button>
      {closing && <span className="notification-burst" aria-hidden="true">{Array.from({ length: 10 }, (_, index) => <i key={index} style={{ "--angle": `${index * 36}deg` } as CSSProperties} />)}</span>}
    </div>
  );
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const push = useCallback((notification: Notification) => {
    setNotifications((current) => [notification, ...current.filter((item) => item.id !== notification.id)].slice(0, 4));
  }, []);
  const dismiss = useCallback((id: string) => setNotifications((current) => current.filter((item) => item.id !== id)), []);
  return (
    <NotificationContext.Provider value={push}>
      {children}
      <div className="notification-popups" aria-label={t("Notifications")}>
        {notifications.map((notification) => <Popup key={notification.id} notification={notification} dismiss={dismiss} />)}
      </div>
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