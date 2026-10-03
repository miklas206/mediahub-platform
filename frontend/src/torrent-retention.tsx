import { useEffect, useId, useRef } from "react";
import { Settings2, X } from "lucide-react";
import { getLocale, t } from "./i18n";
import { ErrorBox } from "./phase2";
import "./torrent-retention.css";

export type RetentionRule = {
  mode: "disabled" | "time" | "ratio" | "both" | "either";
  seedHours: number;
  uploadRatio: number;
  action: "remove_job" | "delete_files";
};
export const defaultRetention: RetentionRule = {
  mode: "disabled",
  seedHours: 48,
  uploadRatio: 2,
  action: "remove_job",
};

export function TorrentRetention({
  value,
  onChange,
  disabled = false,
  supported = true,
}: {
  value: RetentionRule;
  onChange: (rule: RetentionRule) => void;
  disabled?: boolean;
  supported?: boolean;
}) {
  const hoursLabelId = useId();
  const hoursHelpId = useId();
  const ratioLabelId = useId();
  const ratioHelpId = useId();
  return (
    <fieldset disabled={disabled} className="torrent-retention-fields">
      <legend>{t("Automatic cleanup")}</legend>
      <label>
        {t("When to clean up")}
        <select
          value={value.mode}
          disabled={!supported}
          onChange={(e) =>
            onChange({
              ...value,
              mode: e.target.value as RetentionRule["mode"],
              seedHours:
                Number.isInteger(value.seedHours) &&
                value.seedHours >= 1 &&
                value.seedHours <= 8760
                  ? value.seedHours
                  : defaultRetention.seedHours,
              uploadRatio:
                Number.isFinite(value.uploadRatio) &&
                value.uploadRatio >= 0.1 &&
                value.uploadRatio <= 100
                  ? value.uploadRatio
                  : defaultRetention.uploadRatio,
            })
          }
        >
          <option value="disabled">
            {t("Never — keep torrent and files")}
          </option>
          <option value="time">{t("After seeding for a set time")}</option>
          <option value="ratio">{t("After uploading a set ratio")}</option>
          <option value="both">
            {t("After BOTH time and ratio are reached")}
          </option>
          <option value="either">
            {t("After EITHER time or ratio is reached")}
          </option>
        </select>
      </label>
      {!supported && (
        <p className="muted">
          {t("Update the Seedbox Agent to enable cleanup settings.")}
        </p>
      )}
      {value.mode !== "disabled" && (
        <>
          {value.mode !== "ratio" && (
            <label>
              <span id={hoursLabelId}>{t("Seeding time (hours)")}</span>
              <input
                type="number"
                aria-labelledby={hoursLabelId}
                aria-describedby={hoursHelpId}
                min={1}
                max={8760}
                step={1}
                required
                value={Number.isFinite(value.seedHours) ? value.seedHours : ""}
                onChange={(e) =>
                  onChange({ ...value, seedHours: e.target.valueAsNumber })
                }
              />
              <small id={hoursHelpId}>
                {t("Choose from 1 to 8,760 hours.")}
              </small>
            </label>
          )}
          {value.mode !== "time" && (
            <label>
              <span id={ratioLabelId}>{t("Upload ratio")}</span>
              <input
                type="number"
                aria-labelledby={ratioLabelId}
                aria-describedby={ratioHelpId}
                min={0.1}
                max={100}
                step="any"
                required
                value={
                  Number.isFinite(value.uploadRatio) ? value.uploadRatio : ""
                }
                onChange={(e) =>
                  onChange({ ...value, uploadRatio: e.target.valueAsNumber })
                }
              />
              <small id={ratioHelpId}>
                {t("Choose a ratio from 0.1 to 100.")}
              </small>
            </label>
          )}
          <label>
            {t("Cleanup action")}
            <select
              value={value.action}
              onChange={(e) =>
                onChange({
                  ...value,
                  action: e.target.value as RetentionRule["action"],
                })
              }
            >
              <option value="remove_job">
                {t("Remove torrent job — KEEP files")}
              </option>
              <option value="delete_files">
                {t("Remove torrent job AND DELETE files")}
              </option>
            </select>
          </label>
          <p className="muted">
            {t(
              "Only completed downloads are eligible. Time means accumulated seeding time. Ratio 2.0 means 200 MB uploaded for 100 MB of content. Checked every minute.",
            )}
          </p>
          {value.action === "delete_files" && (
            <p role="note" className="notice">
              {t(
                "The downloaded files will be permanently deleted from storage, including files used by Plex. Shared files or unsafe paths block deletion.",
              )}
            </p>
          )}
        </>
      )}
      {value.mode === "disabled" && (
        <p className="muted">
          {t(
            "Automatic cleanup is off. The torrent job and its files will be kept.",
          )}
        </p>
      )}
    </fieldset>
  );
}

export function retentionSummary(rule: RetentionRule) {
  if (rule.mode === "disabled") return t("Never — keep torrent and files");
  const hours = rule.seedHours.toLocaleString(getLocale());
  const ratio = rule.uploadRatio.toLocaleString(getLocale(), {
    maximumFractionDigits: 20,
    useGrouping: false,
  });
  const threshold = {
    time: t("After {hours} hours of seeding", { hours }),
    ratio: t("After upload ratio {ratio}", { ratio }),
    both: t("After {hours} hours AND ratio {ratio}", { hours, ratio }),
    either: t("After {hours} hours OR ratio {ratio}", { hours, ratio }),
  }[rule.mode];
  return t("Cleanup: {mode} · {action}", {
    mode: threshold,
    action:
      rule.action === "delete_files" ? t("deletes files") : t("keeps files"),
  });
}

export function TorrentCleanupDialog({
  name,
  value,
  onChange,
  onSave,
  onCancel,
  busy,
  error,
}: {
  name: string;
  value: RetentionRule;
  onChange: (rule: RetentionRule) => void;
  onSave: () => void;
  onCancel: () => void;
  busy: boolean;
  error: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => {
    const element = dialog.current;
    const trigger = document.activeElement;
    element?.showModal();
    element?.querySelector<HTMLSelectElement>("select")?.focus();
    return () => {
      element?.close();
      if (trigger instanceof HTMLElement && trigger.isConnected)
        trigger.focus();
    };
  }, []);

  return (
    <dialog
      ref={dialog}
      className="torrent-cleanup-dialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      aria-busy={busy}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <header className="torrent-cleanup-heading">
        <Settings2 size={20} strokeWidth={1.75} aria-hidden="true" />
        <h2 id={titleId}>{t("Torrent cleanup settings")}</h2>
        <button
          type="button"
          className="topbar-action"
          aria-label={t("Close")}
          disabled={busy}
          onClick={onCancel}
        >
          <X size={18} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </header>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!busy) onSave();
        }}
      >
        <p className="torrent-cleanup-name">{name}</p>
        <p className="muted" id={descriptionId}>
          {t(
            "Save a rule for this torrent only. It replaces any cleanup rule copied from a feed without changing the feed or other torrents.",
          )}
        </p>
        <TorrentRetention value={value} onChange={onChange} disabled={busy} />
        {value.mode !== "disabled" && (
          <p className="muted">
            {t(
              "Applies to this torrent's existing seeding time and uploaded bytes. If its thresholds are already reached, cleanup can run on the next check.",
            )}
          </p>
        )}
        <ErrorBox error={error} />
        <footer className="torrent-cleanup-actions">
          <button type="button" disabled={busy} onClick={onCancel}>
            {t("Cancel")}
          </button>
          <button type="submit" className="primary" disabled={busy}>
            {busy ? t("Saving…") : t("Save cleanup settings")}
          </button>
        </footer>
      </form>
    </dialog>
  );
}

export function retentionModeLabel(mode: RetentionRule["mode"]) {
  return t(
    {
      disabled: "No automatic cleanup",
      time: "After time",
      ratio: "After ratio",
      both: "After time and ratio",
      either: "After time or ratio",
    }[mode],
  );
}
