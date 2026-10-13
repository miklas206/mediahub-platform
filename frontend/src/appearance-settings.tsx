import { ColorWheel } from "./color-wheel";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";
import {
  Check,
  Palette,
  RotateCcw,
  SlidersHorizontal,
  List,
  Activity,
  SunMoon,
} from "lucide-react";
import { api } from "./api";
import { t, translateText } from "./i18n";
import { NotificationPopup } from "./notification-popup";
import { useConfirm } from "./confirmation-dialog";
import { themePresets } from "./theme-presets";
import {
  clearAppearancePreview,
  appearanceTokens,
  applySavedAppearance,
  beginAppearanceSave,
  defaultAppearance,
  finishAppearanceSave,
  isHexColor,
  previewAppearance,
  useAppearance,
  useAppearanceSaving,
  type Appearance,
} from "./appearance";
import "./appearance-settings.css";

const presets: { name: string; value: Appearance | null }[] = [
  { name: "MediaHub", value: null },
  {
    name: "Ocean",
    value: {
      accent: "#20cfde",
      secondary: "#5c9bff",
      background: "#16446b",
      depth: 35,
    },
  },
  {
    name: "Violet",
    value: {
      accent: "#b899ff",
      secondary: "#ed88c0",
      background: "#342451",
      depth: 35,
    },
  },
  {
    name: "Rose",
    value: {
      accent: "#f391b9",
      secondary: "#a899ff",
      background: "#422d3d",
      depth: 40,
    },
  },
  {
    name: "Graphite",
    value: {
      accent: "#b6c6e2",
      secondary: "#85bfff",
      background: "#282828",
      depth: 25,
    },
  },
];
const fields = [
  ["accent", "Accent color"],
  ["secondary", "Secondary color"],
  ["background", "Background tone"],
] as const;
const same = (a: Appearance | null, b: Appearance | null) =>
  JSON.stringify(a) === JSON.stringify(b);

export function AppearanceSettings({ compact = false }: { compact?: boolean }) {
  const confirm = useConfirm();
  const saved = useAppearance();
  const [draft, setDraft] = useState(saved);
  const [inputs, setInputs] = useState(saved || defaultAppearance);
  const busy = useAppearanceSaving();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [toastPreview, setToastPreview] = useState(0);
  const mounted = useRef(true);
  useEffect(() => {
    setDraft(saved);
    setInputs(saved || defaultAppearance);
  }, [saved]);
  useEffect(() => {
    previewAppearance(draft);
  }, [draft]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      clearAppearancePreview();
    };
  }, []);
  const invalid = fields.some(([key]) => !isHexColor(inputs[key]));
  const dirty = !same(saved, draft) || invalid;
  const availablePresets =
    saved && !presets.some((preset) => same(saved, preset.value))
      ? [...presets, { name: "Saved palette", value: saved }]
      : presets;
  function choose(value: Appearance | null) {
    setDraft(value);
    setInputs(value || defaultAppearance);
    setError("");
    setMessage("");
  }
  function choosePalette(value: Appearance | null) {
    const current = draft || defaultAppearance;
    choose({
      ...(value || defaultAppearance),
      style: current.style,
      mode: current.mode,
      density: current.density,
      reducedMotion: current.reducedMotion,
    });
  }
  function changeColor(key: (typeof fields)[number][0], value: string) {
    setInputs((current) => ({ ...current, [key]: value }));
    setMessage("");
    if (isHexColor(value))
      setDraft((current) => ({
        ...(current || defaultAppearance),
        [key]: value.toLowerCase(),
      }));
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (invalid || busy) return;
    const session = beginAppearanceSave();
    if (session === null) return;
    setError("");
    setMessage("");
    try {
      const preferences = await api<{ appearance: Appearance | null }>(
        "/auth/preferences",
        "PUT",
        { appearance: draft },
      );
      if (
        applySavedAppearance(preferences.appearance, session) &&
        mounted.current
      )
        setMessage("Your appearance has been saved.");
    } catch (failure) {
      if (mounted.current) setError((failure as Error).message);
    } finally {
      finishAppearanceSave(session);
    }
  }
  const selectedStyle = draft?.style || "midnight-glass";
  const quickThemes = themePresets.filter((preset) => preset.id !== "classic");
  const preview = (preset: (typeof themePresets)[number]) => {
    const value = preset.value || defaultAppearance;
    const palette = appearanceTokens(value, true);
    return (
      <span
        className="theme-mini"
        data-style={preset.id}
        aria-hidden="true"
        style={
          {
            "--sample-bg": palette["--bg"],
            "--sample-surface": palette["--surface"],
            "--sample-raised": palette["--raised"],
            "--sample-accent": palette["--accent"],
          } as CSSProperties
        }
      >
        <span className="theme-mini-nav">
          <i />
          <i />
          <i />
          <i />
        </span>
        <span className="theme-mini-content">
          <i />
          <span>
            <i />
            <i />
          </span>
          <i />
          <i />
          <span className="mini-buttons">
            <i />
            <i />
          </span>
        </span>
      </span>
    );
  };
  return (
    <section className="appearance-settings reference-appearance">
      <form onSubmit={(event) => void save(event)}>
        <h2 className="appearance-section-label">{t("Themes")}</h2>
        <div className="theme-gallery" role="group" aria-label={t("Themes")}>
          {quickThemes.map((preset) => (
            <button
              type="button"
              className="theme-choice"
              key={preset.id}
              disabled={busy}
              aria-pressed={selectedStyle === preset.id}
              onClick={() =>
                choose({
                  ...preset.value!,
                  mode: draft?.mode || preset.value!.mode,
                  reducedMotion: draft?.reducedMotion ?? false,
                })
              }
            >
              <span className="theme-preview-frame">
                {preview(preset)}
                {selectedStyle === preset.id && (
                  <span className="theme-selected">
                    <Check size={13} />
                  </span>
                )}
              </span>
              <strong>{preset.name}</strong>
              <small>{t(preset.description)}</small>
            </button>
          ))}
        </div>
        <div className="appearance-interface">
          <h2 className="appearance-section-label">{t("Interface options")}</h2>
          <div className="appearance-option-grid">
            <label className="appearance-option">
              <List size={20} />
              <span>
                <strong>{t("Compact layout")}</strong>
                <small>{t("Show more content, reduce spacing.")}</small>
              </span>
              <input
                className="appearance-toggle"
                type="checkbox"
                disabled={busy}
                checked={draft?.density === "compact"}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...(current || defaultAppearance),
                    density: event.target.checked ? "compact" : "comfortable",
                  }))
                }
              />
            </label>
            <label className="appearance-option">
              <Activity size={20} />
              <span>
                <strong>{t("Reduce motion")}</strong>
                <small>{t("Minimize animations and transitions.")}</small>
              </span>
              <input
                className="appearance-toggle"
                type="checkbox"
                disabled={busy}
                checked={draft?.reducedMotion ?? false}
                onChange={(event) =>
                  setDraft((current) => ({
                    ...(current || defaultAppearance),
                    reducedMotion: event.target.checked,
                  }))
                }
              />
            </label>
            <div className="appearance-option appearance-accent">
              <Palette size={20} />
              <span>
                <strong>{t("Accent color")}</strong>
                <small>{t("Choose your highlight color.")}</small>
              </span>
              <div
                className="accent-dots"
                role="group"
                aria-label={t("Accent color")}
              >
                {["#25c9ed", "#4be0ab", "#508dff", "#aa69ef"].map((color) => (
                  <button
                    type="button"
                    key={color}
                    disabled={busy}
                    aria-label={color}
                    aria-pressed={(draft || defaultAppearance).accent === color}
                    style={{ backgroundColor: color }}
                    onClick={() => changeColor("accent", color)}
                  />
                ))}
                <ColorWheel
                  color={(draft || defaultAppearance).accent}
                  onChange={(color) => changeColor("accent", color)}
                  disabled={busy}
                />
              </div>
            </div>
            <div className="appearance-option appearance-mode">
              <SunMoon size={20} />
              <label>
                <strong>{t("Color mode")}</strong>
                <select
                  aria-label={t("Color mode")}
                  disabled={busy}
                  value={draft?.mode || "inherit"}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...(current || defaultAppearance),
                      mode: event.target.value as Appearance["mode"],
                    }))
                  }
                >
                  <option value="inherit">{t("Follow workspace")}</option>
                  <option value="dark">{t("Dark")}</option>
                  <option value="light">{t("Light")}</option>
                  <option value="system">{t("System")}</option>
                </select>
              </label>
            </div>
          </div>
        </div>
        <div className="theme-try-actions">
          <button
            type="button"
            onClick={() =>
              void confirm(
                t(
                  "This is a theme preview. No settings or services will be changed.",
                ),
                { title: "Theme preview", confirmLabel: "Looks good" },
              )
            }
          >
            {t("Preview dialog")}
          </button>
          <button
            type="button"
            onClick={() => setToastPreview((current) => current + 1)}
          >
            {t("Preview notification")}
          </button>
        </div>
        <div className="appearance-quick-save">
          <button
            type="submit"
            className="primary"
            disabled={busy || invalid || !dirty}
          >
            {t(busy ? "Saving…" : "Save")}
          </button>
          <button
            type="button"
            disabled={busy || !dirty}
            onClick={() => choose(saved)}
          >
            {t("Discard changes")}
          </button>
          <button type="button" disabled={busy} onClick={() => choose(null)}>
            <RotateCcw size={14} />
            {t("Defaults")}
          </button>
        </div>
        <details className="appearance-advanced">
          <summary>{t("Advanced coloring")}</summary>
          <div
            className="appearance-presets"
            role="group"
            aria-label={t("Color palettes")}
          >
            {availablePresets.map((preset) => (
              <button
                key={preset.name}
                type="button"
                disabled={busy}
                aria-pressed={[
                  "accent",
                  "secondary",
                  "background",
                  "depth",
                ].every(
                  (key) =>
                    (draft || defaultAppearance)[key as keyof Appearance] ===
                    (preset.value || defaultAppearance)[
                      key as keyof Appearance
                    ],
                )}
                onClick={() => choosePalette(preset.value)}
              >
                <span className="palette-swatches" aria-hidden="true">
                  {[
                    preset.value?.accent || defaultAppearance.accent,
                    preset.value?.secondary || defaultAppearance.secondary,
                    preset.value?.background || defaultAppearance.background,
                  ].map((color, index) => (
                    <span key={index} style={{ backgroundColor: color }} />
                  ))}
                </span>
                {t(preset.name)}
              </button>
            ))}
          </div>
          <div className="appearance-controls">
            {fields.map(([key, label]) => (
              <div className="appearance-color-field" key={key}>
                <label htmlFor={`appearance-${key}`}>{t(label)}</label>
                <div>
                  <input
                    id={`appearance-${key}`}
                    type="color"
                    value={(draft || defaultAppearance)[key]}
                    aria-label={t(label)}
                    disabled={busy}
                    onChange={(event) => changeColor(key, event.target.value)}
                  />
                  <input
                    type="text"
                    aria-label={t("{name} (hex)", { name: t(label) })}
                    value={inputs[key]}
                    maxLength={7}
                    pattern="#[0-9a-fA-F]{6}"
                    spellCheck={false}
                    aria-invalid={!isHexColor(inputs[key])}
                    disabled={busy}
                    onChange={(event) => changeColor(key, event.target.value)}
                  />
                </div>
                {!isHexColor(inputs[key]) && (
                  <small className="field-error">
                    {t("Use a six-digit hex color, such as #25c9ed.")}
                  </small>
                )}
              </div>
            ))}
          </div>
          {!compact && (
            <>
              <div className="appearance-depth">
                <label htmlFor="appearance-depth">
                  <SlidersHorizontal size={15} />
                  {t("Shade intensity")}
                  <output htmlFor="appearance-depth">
                    {(draft || defaultAppearance).depth}%
                  </output>
                </label>
                <input
                  id="appearance-depth"
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  value={(draft || defaultAppearance).depth}
                  disabled={busy}
                  onChange={(event) => {
                    setDraft((current) => ({
                      ...(current || defaultAppearance),
                      depth: Number(event.target.value),
                    }));
                    setMessage("");
                  }}
                />
                <small>
                  {t(
                    "Backgrounds and cards follow your chosen tone in both light and dark mode. Text contrast adjusts automatically.",
                  )}
                </small>
              </div>
              <div
                className="appearance-preview"
                aria-label={t("Color preview")}
              >
                <div className="appearance-preview-head">
                  <strong>MediaHub</strong>
                  <span className="badge healthy">
                    <Check size={12} />
                    {t("Healthy")}
                  </span>
                </div>
                <div className="appearance-preview-card">
                  <Palette size={21} />
                  <div>
                    <strong>{t("Your personal palette")}</strong>
                    <small>
                      {t("Buttons, cards and charts use your colors.")}
                    </small>
                  </div>
                </div>
                <div className="appearance-preview-actions" aria-hidden="true">
                  <span className="preview-primary">{t("Primary")}</span>
                  <span className="preview-secondary">{t("Secondary")}</span>
                  <span className="preview-warning">{t("Warning")}</span>
                  <span className="preview-error">{t("Error")}</span>
                </div>
              </div>
              <p className="appearance-description">
                {t(
                  "Green, yellow and red keep their meaning for online status, warnings and errors.",
                )}
              </p>
            </>
          )}
        </details>
        {error && (
          <NotificationPopup tone="danger">
            {translateText(error)}
          </NotificationPopup>
        )}
        {message && (
          <NotificationPopup tone="success">{t(message)}</NotificationPopup>
        )}
        {toastPreview > 0 && (
          <NotificationPopup key={toastPreview} tone="info">
            {t("Theme preview · this is how notifications look.")}
          </NotificationPopup>
        )}
      </form>
    </section>
  );
}
