import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Cpu, MemoryStick, Settings2, Check, X } from "lucide-react";
import { api } from "./api";
import { bytes } from "./format";
import { getLocale, t, translateText } from "./i18n";
import { useData } from "./use-data";
import { NotificationPopup } from "./notification-popup";
import { ServiceIcon } from "./service-icon";
import "./app-resources.css";

const GiB = 1024 ** 3;
type Limits = { memoryBytes: number | null; cpuCores: number | null };
export type ResourceAdvice = {
  id: string;
  metric: keyof Limits;
  direction: "increase" | "decrease";
  current: number;
  proposed: number;
  peak: number;
  windowDays: number;
  feasible: boolean;
};
export type AppResource = {
  id: string;
  packageId: string;
  name: string;
  available: boolean;
  editable: boolean;
  canRemoveCpuLimit?: boolean;
  operation?: { state: string; message: string } | null;
  reason?: string;
  revision?: string;
  running?: boolean;
  sampledAt?: number;
  memoryBytes?: number | null;
  cpuCores?: number | null;
  limits?: Limits;
  recommendationsEnabled: boolean;
  recommendations: ResourceAdvice[];
  sharedExcluded?: boolean;
  host?: { memoryBytes: number; cpuCores: number };
  history?: {
    samples: number;
    days: number;
    peakMemoryBytes: number | null;
    peakCpuCores: number | null;
  };
};
const number = (value: number) =>
  value.toLocaleString(getLocale(), { maximumFractionDigits: 2 });
const amount = (metric: keyof Limits, value: number) =>
  metric === "memoryBytes"
    ? bytes(value)
    : `${number(value)} ${t("CPU cores")}`;
export function adviceText(row: AppResource, advice: ResourceAdvice) {
  return t(
    advice.direction === "increase"
      ? "{name} is limited to {assigned} and repeatedly peaks at {peak}. Increase to {proposed}."
      : "{name} is limited to {assigned} and peaked at only {peak} during seven days. Reduce to {proposed}.",
    {
      name: row.name,
      assigned: amount(advice.metric, advice.current),
      peak: amount(advice.metric, advice.peak),
      proposed: amount(advice.metric, advice.proposed),
    },
  );
}
function usage(
  used: number | null | undefined,
  limit: number | null | undefined,
) {
  return used != null && limit
    ? Math.max(0, Math.min(100, (used / limit) * 100))
    : undefined;
}

export function ResourceCard({
  row,
  reload,
  settings = false,
}: {
  row: AppResource;
  reload: () => void;
  settings?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [ram, setRam] = useState("");
  const [cpu, setCpu] = useState("");
  const [revision, setRevision] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  function edit() {
    setRam(row.limits?.memoryBytes ? String(row.limits.memoryBytes / GiB) : "");
    setCpu(row.limits?.cpuCores ? String(row.limits.cpuCores) : "");
    setRevision(row.revision || "");
    setEditing(true);
  }
  async function change(event?: FormEvent, advice?: ResourceAdvice) {
    event?.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const limits: Limits = advice
        ? { ...row.limits!, [advice.metric]: advice.proposed }
        : {
            memoryBytes: ram.trim() ? Math.round(Number(ram) * GiB) : null,
            cpuCores: cpu.trim() ? Number(cpu) : null,
          };
      await api(
        `/resources/${encodeURIComponent(row.id)}${advice ? "/approve" : ""}`,
        advice ? "POST" : "PUT",
        {
          ...limits,
          revision: advice ? row.revision : revision,
          ...(advice ? { recommendationId: advice.id } : {}),
        },
      );
      setEditing(false);
      setNotice("Resource limits saved and verified.");
      reload();
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function preference(enabled: boolean) {
    setBusy(true);
    setError("");
    try {
      await api(
        `/resources/${encodeURIComponent(row.id)}/recommendations`,
        "PUT",
        { enabled },
      );
      reload();
      setNotice(
        enabled
          ? "Resource recommendations enabled."
          : "Resource recommendations disabled. Manual editing remains available.",
      );
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="app-resource-card">
      {error && <NotificationPopup tone="danger">{error}</NotificationPopup>}
      {notice && <NotificationPopup tone="success">{notice}</NotificationPopup>}
      <header>
        <ServiceIcon packageId={row.packageId} size={25} />
        <div>
          <strong>{row.name}</strong>
          <small>
            {t(
              !row.available
                ? "Measurements unavailable"
                : row.running
                  ? "Running"
                  : "Stopped",
            )}
          </small>
        </div>
        <button
          onClick={edit}
          disabled={!row.editable || busy || !row.available}
          aria-label={t("Edit resources for {name}", { name: row.name })}
        >
          <Settings2 size={16} />
          {t("Edit resources")}
        </button>
      </header>
      {row.operation &&
        ["interrupted", "recovery_failed"].includes(row.operation.state) && (
          <p className="resource-prerequisite">
            {translateText(row.operation.message)}
          </p>
        )}
      {row.available && row.limits ? (
        <>
          <div className="app-resource-measurements">
            <div>
              <span>
                <MemoryStick size={16} />
                {t("RAM")}
              </span>
              <strong>
                {row.memoryBytes == null
                  ? t("No live measurement")
                  : bytes(row.memoryBytes)}
              </strong>
              <small>
                {t("Limit")}:{" "}
                {row.limits.memoryBytes
                  ? bytes(row.limits.memoryBytes)
                  : t("No limit - shared host capacity")}
              </small>
              <progress
                aria-label={t("RAM usage against limit")}
                max={100}
                value={usage(row.memoryBytes, row.limits.memoryBytes)}
                data-pressure={
                  usage(row.memoryBytes, row.limits.memoryBytes)! >= 90
                }
              />
              <small>
                {t("Observed peak")}:{" "}
                {row.history?.peakMemoryBytes == null
                  ? "-"
                  : bytes(row.history.peakMemoryBytes)}
              </small>
            </div>
            <div>
              <span>
                <Cpu size={16} />
                {t("CPU")}
              </span>
              <strong>
                {row.cpuCores == null
                  ? t("No live measurement")
                  : `${number(row.cpuCores)} ${t("CPU cores")}`}
              </strong>
              <small>
                {t("Limit")}:{" "}
                {row.limits.cpuCores
                  ? `${number(row.limits.cpuCores)} ${t("CPU cores")}`
                  : t("No limit - shared host capacity")}
              </small>
              <progress
                aria-label={t("CPU usage against limit")}
                max={100}
                value={usage(row.cpuCores, row.limits.cpuCores)}
                data-pressure={usage(row.cpuCores, row.limits.cpuCores)! >= 90}
              />
              <small>
                {t("Observed peak")}:{" "}
                {row.history?.peakCpuCores == null
                  ? "-"
                  : `${number(row.history.peakCpuCores)} ${t("CPU cores")}`}
              </small>
            </div>
          </div>
          <p className="muted resource-history-note">
            {t(
              "History collected: {days} days. Reductions require seven days of reliable measurements.",
              { days: number(row.history?.days || 0) },
            )}
          </p>
          {row.sharedExcluded && (
            <p className="muted resource-history-note">
              {t(
                "Shared VPN infrastructure is shown separately and is not counted in this app's limits.",
              )}
            </p>
          )}
        </>
      ) : (
        <p className="muted">
          {translateText(row.reason || "Collecting app resource measurements.")}
        </p>
      )}
      {row.available && !row.editable && row.reason && (
        <p className="resource-prerequisite">
          {translateText(row.reason)}{" "}
          <Link to="/settings?section=Updates">{t("Open Updates")}</Link>
        </p>
      )}
      {editing && (
        <form
          className="resource-editor"
          onSubmit={(event) => void change(event)}
        >
          <p className="muted">
            {t(
              "Limits are ceilings, not reserved resources. Leave a field empty to share host capacity without a limit.",
            )}
          </p>
          <div>
            <label>
              {t("RAM limit (GiB)")}
              <input
                type="number"
                min="0.25"
                step="0.25"
                value={ram}
                onChange={(event) => setRam(event.target.value)}
                placeholder={t("No limit")}
              />
            </label>
            <label>
              {t("CPU limit (cores)")}
              <input
                type="number"
                min="0.25"
                step="0.25"
                required={
                  !!row.limits?.cpuCores && row.canRemoveCpuLimit === false
                }
                value={cpu}
                onChange={(event) => setCpu(event.target.value)}
                placeholder={t("No limit")}
              />
            </label>
          </div>
          <p className="muted">
            {t(
              "Changes apply live when supported. Capacity, ownership and current usage are checked before saving.",
            )}
          </p>
          {row.canRemoveCpuLimit === false && (
            <p className="muted">
              {t(
                "This existing CPU limit can be adjusted live. Removing it requires recreating the app container.",
              )}
            </p>
          )}
          <div className="button-row">
            <button type="submit" disabled={busy}>
              {t(busy ? "Saving..." : "Save resources")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setEditing(false)}
            >
              <X size={15} />
              {t("Cancel")}
            </button>
          </div>
        </form>
      )}
      {row.recommendations?.map((advice) => (
        <div key={advice.id} className="resource-advice">
          <p>{adviceText(row, advice)}</p>
          <small>
            {t(
              advice.direction === "increase"
                ? "Based on repeated peaks in the last hour. Capacity is checked again on approval."
                : "Based on seven days with at least 80% measurement coverage, including observed peaks.",
            )}
          </small>
          <button
            disabled={busy || !row.editable || !advice.feasible}
            onClick={() => void change(undefined, advice)}
          >
            <Check size={16} />
            {t("Approve")}
          </button>
          {!advice.feasible && (
            <small>
              {t(
                "The host lacks capacity for this proposal. Adjust limits manually or add host capacity.",
              )}
            </small>
          )}
        </div>
      ))}
      {settings ? (
        <label className="resource-preference">
          <input
            type="checkbox"
            checked={row.recommendationsEnabled}
            disabled={busy}
            onChange={(event) => void preference(event.target.checked)}
          />
          {t("Resource recommendations")}
        </label>
      ) : (
        <Link
          className="text-link resource-settings-link"
          to={`/app-settings/${encodeURIComponent(row.packageId)}`}
        >
          {t("App resource settings")}
        </Link>
      )}
    </article>
  );
}

export function AppResourceOverview() {
  const data = useData<{
    items: AppResource[];
    shared?: {
      name: string;
      memoryBytes: number | null;
      cpuCores: number | null;
      components?: { name: string; memoryBytes: number | null; cpuCores: number | null }[];
    }[];
  }>("/resources");
  const reload = data.reload;
  const poll = data.poll;
  const seen = useRef(new Set<string>());
  const [popup, setPopup] = useState<{
    row: AppResource;
    advice: ResourceAdvice;
  }>();
  const [approving, setApproving] = useState(false);
  const [failure, setFailure] = useState("");
  async function approvePopup() {
    if (!popup) return;
    setApproving(true);
    setFailure("");
    try {
      await api(
        `/resources/${encodeURIComponent(popup.row.id)}/approve`,
        "POST",
        {
          ...popup.row.limits,
          [popup.advice.metric]: popup.advice.proposed,
          revision: popup.row.revision,
          recommendationId: popup.advice.id,
        },
      );
      setPopup(undefined);
      reload();
    } catch (error) {
      setFailure((error as Error).message);
    } finally {
      setApproving(false);
    }
  }
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) poll();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [poll]);
  useEffect(() => {
    for (const row of data.data?.items || [])
      for (const advice of row.recommendations || [])
        if (!seen.current.has(advice.id)) {
          seen.current.add(advice.id);
          setPopup({ row, advice });
          return;
        }
  }, [data.data]);
  return (
    <section className="app-resource-overview" aria-label={t("App resources")}>
      <header>
        <div>
          <h2>{t("App resources")}</h2>
          <p className="muted">
            {t(
              "Current usage, assigned limits and recommendations for local installed apps.",
            )}
          </p>
          <small className="muted">{t("App measurements update about once a minute. RAM excludes file cache; peak is historical usage.")}</small>
        </div>
        <button onClick={reload}>{t("Refresh")}</button>
      </header>
      <p className="muted">{t("The total also includes MediaHub, local support services and the operating system. App measurements refresh less often, so the figures need not add up exactly.")}</p>
      {(data.error || failure) && (
        <NotificationPopup tone="danger">
          {data.error || failure}
        </NotificationPopup>
      )}
      {popup && (
        <NotificationPopup key={popup.advice.id} tone="info">
          <span>{adviceText(popup.row, popup.advice)}</span>
          <button
            disabled={approving || !popup.advice.feasible}
            onClick={() => void approvePopup()}
          >
            {t("Approve")}
          </button>
          <a href="#app-resource-list">{t("Review and approve")}</a>
        </NotificationPopup>
      )}
      <div id="app-resource-list" className="app-resource-grid">
        {data.data?.items?.map((row) => (
          <ResourceCard key={row.id} row={row} reload={reload} />
        ))}
      </div>
      {!data.data && !data.error && (
        <p className="muted">{t("Collecting app resource measurements.")}</p>
      )}
      {data.data?.items?.length === 0 && (
        <p className="muted">{t("No local apps with resource telemetry are installed.")}</p>
      )}
      {data.data?.shared?.map((row) => (
        <div key={row.name} className="resource-shared">
          <strong>{t(row.name)}</strong>
          <span>
            {t("RAM")}: {row.memoryBytes == null ? "-" : bytes(row.memoryBytes)}
          </span>
          <span>
            {t("CPU")}:{" "}
            {row.cpuCores == null
              ? "-"
              : `${number(row.cpuCores)} ${t("CPU cores")}`}
          </span>
          <small>
            {t(
              row.name === "Shared VPN infrastructure" ? "Shared by multiple apps. Shown once; limits require coordination of the shared service." : "Local MediaHub services are measured separately from app limits.",
            )}
          </small>
          {!!row.components?.length && <details><summary>{t("Included services")}</summary><ul>{row.components.map((component, index) => <li key={`${component.name}-${index}`}>{t(component.name)}: {component.memoryBytes == null ? "—" : bytes(component.memoryBytes)} · {component.cpuCores == null ? "—" : `${number(component.cpuCores)} ${t("CPU cores")}`}</li>)}</ul></details>}
        </div>
      ))}
    </section>
  );
}

export function AppResourceSettings({ appId }: { appId: string }) {
  const data = useData<AppResource>(`/resources/${encodeURIComponent(appId)}`);
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>{t("Resources")}</h2>
      </div>
      <div className="phase-content">
        {data.error && (
          <NotificationPopup tone="danger">{data.error}</NotificationPopup>
        )}
        {data.data && (
          <ResourceCard row={data.data} reload={data.reload} settings />
        )}
      </div>
    </section>
  );
}
