import { t } from "./i18n";
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
  return (
    <fieldset
      disabled={disabled}
      style={{
        border: "1px solid var(--line)",
        borderRadius: 8,
        padding: 14,
        margin: "16px 0",
      }}
    >
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
              {t("Seeding time")}
              <select
                value={value.seedHours}
                onChange={(e) =>
                  onChange({ ...value, seedHours: Number(e.target.value) })
                }
              >
                {[24, 48, 72, 168, 336, 720].map((h) => (
                  <option value={h} key={h}>
                    {h / 24}
                    {t(" day(s) / ")}
                    {h}
                    {t(" hours")}
                  </option>
                ))}
              </select>
            </label>
          )}
          {value.mode !== "time" && (
            <label>
              {t("Upload ratio")}
              <select
                value={value.uploadRatio}
                onChange={(e) =>
                  onChange({ ...value, uploadRatio: Number(e.target.value) })
                }
              >
                {[1, 1.5, 2, 3, 5].map((r) => (
                  <option key={r} value={r}>
                    {r.toFixed(1)}
                    {t(" — upload ")}
                    {r}
                    {t("× the content size")}
                  </option>
                ))}
              </select>
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
    </fieldset>
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
