import { Children, createContext, isValidElement, useCallback, useContext, useEffect, useLayoutEffect, useId, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";
import { t } from "./i18n";
import "./notification-popup.css";

type Tone = "danger" | "warning" | "info" | "success";
type Notification = { id: string; message: ReactNode; tone: Tone };
const NotificationContext = createContext<(notification: Notification) => void>(() => {});
const fragments = [
  ["0 0, 27% 0, 23% 43%, 0 58%", -90, -60, -18],
  ["27% 0, 51% 0, 48% 57%, 23% 43%", -35, -85, 12],
  ["51% 0, 76% 0, 73% 46%, 48% 57%", 35, -75, -14],
  ["76% 0, 100% 0, 100% 55%, 73% 46%", 90, -55, 20],
  ["0 58%, 23% 43%, 29% 100%, 0 100%", -80, 65, 16],
  ["23% 43%, 48% 57%, 52% 100%, 29% 100%", -30, 90, -12],
  ["48% 57%, 73% 46%, 78% 100%, 52% 100%", 35, 80, 18],
  ["73% 46%, 100% 55%, 100% 100%, 78% 100%", 85, 60, -16],
] as const;

function messageText(message: ReactNode): string {
  return Children.toArray(message).map((child) =>
    isValidElement<{ children?: ReactNode }>(child) ? messageText(child.props.children) : String(child),
  ).join("");
}

function Popup({ notification, dismiss }: { notification: Notification; dismiss: (id: string) => void }) {
  const [paused, setPaused] = useState(false);
  const [closing, setClosing] = useState(false);
  const surface = useRef<HTMLDivElement>(null);
  const burst = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    if (!closing || !surface.current || !burst.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const layer = burst.current;
    for (const [polygon, horizontal, vertical, rotation] of fragments) {
      const piece = document.createElement("span");
      piece.className = "notification-fragment";
      piece.style.setProperty("--fragment-x", `${horizontal}px`);
      piece.style.setProperty("--fragment-y", `${vertical}px`);
      piece.style.setProperty("--fragment-rotation", `${rotation}deg`);
      const copy = surface.current.cloneNode(true) as HTMLDivElement;
      copy.querySelector(".notification-burst")?.remove();
      copy.querySelectorAll("[id]").forEach((element) => element.removeAttribute("id"));
      copy.removeAttribute("role");
      copy.classList.remove("is-popping");
      copy.classList.add("notification-shard");
      copy.inert = true;
      copy.style.clipPath = `polygon(${polygon})`;
      piece.append(copy);
      layer.append(piece);
    }
    return () => layer.replaceChildren();
  }, [closing]);
  const remaining = useRef(notification.tone === "danger" ? 9000 : 6000);
  useEffect(() => {
    if (closing) {
      const timer = window.setTimeout(() => dismiss(notification.id), window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 760);
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
    <div ref={surface} className={`notification-popup ${notification.tone}${closing ? " is-popping" : ""}`} data-paused={paused} role={notification.tone === "danger" ? "alert" : "status"}
      onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setPaused(false); }}>
      <span className="notification-code" aria-hidden="true">
        {Array.from({ length: 8 }, (_, index) => <span key={index} style={{ left: `${index * 13}%`, animationDelay: `${index * -0.7}s` }}>{index % 2 ? "10:01\n0011\n01:10\n1100\n1010" : "0101\n11:00\n1001\n00:11\n0110"}</span>)}
      </span>
      <Icon size={19} aria-hidden="true" />
      <div className="notification-message">{notification.message}</div>
      <button type="button" disabled={closing} aria-label={t("Dismiss notification")} title={t("Dismiss notification")} onClick={() => setClosing(true)}><X size={16} /></button>
      <span className="notification-lifetime" aria-hidden="true" style={{ animationDuration: notification.tone === "danger" ? "9s" : "6s" }} />
      {closing && <span ref={burst} className="notification-burst" aria-hidden="true" />}
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