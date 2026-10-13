import { useEffect, useId, useRef, useState, type PointerEvent } from "react";
import { createPortal } from "react-dom";
import { Palette, X } from "lucide-react";
import { t } from "./i18n";
import { isHexColor } from "./appearance";
import "./color-wheel.css";

export type HSV = { h: number; s: number; v: number };
export function hexToHSV(hex: string): HSV {
  const [r, g, b] = [1, 3, 5].map(
    (offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255,
  );
  const max = Math.max(r, g, b),
    min = Math.min(r, g, b),
    delta = max - min;
  const raw = !delta
    ? 0
    : max === r
      ? ((g - b) / delta) % 6
      : max === g
        ? (b - r) / delta + 2
        : (r - g) / delta + 4;
  return {
    h: (raw * 60 + 360) % 360,
    s: max ? (delta / max) * 100 : 0,
    v: max * 100,
  };
}
export function hsvToHex({ h, s, v }: HSV) {
  const hue = ((h % 360) + 360) % 360,
    saturation = Math.max(0, Math.min(100, s)) / 100,
    value = Math.max(0, Math.min(100, v)) / 100;
  const c = value * saturation,
    x = c * (1 - Math.abs(((hue / 60) % 2) - 1)),
    m = value - c;
  const rgb =
    hue < 60
      ? [c, x, 0]
      : hue < 120
        ? [x, c, 0]
        : hue < 180
          ? [0, c, x]
          : hue < 240
            ? [0, x, c]
            : hue < 300
              ? [x, 0, c]
              : [c, 0, x];
  return (
    "#" +
    rgb
      .map((channel) =>
        Math.round((channel + m) * 255)
          .toString(16)
          .padStart(2, "0"),
      )
      .join("")
  );
}
export function ColorWheel({
  color,
  onChange,
  disabled = false,
}: {
  color: string;
  onChange: (color: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false),
    [hsv, setHSV] = useState(() => hexToHSV(color)),
    [hex, setHex] = useState(color);
  const original = useRef(color),
    dialog = useRef<HTMLDialogElement>(null),
    trigger = useRef<HTMLButtonElement>(null),
    id = useId();
  useEffect(() => {
    if (open) dialog.current?.showModal();
  }, [open]);
  function begin() {
    original.current = color;
    setHSV(hexToHSV(color));
    setHex(color);
    setOpen(true);
  }
  function close(cancel = false) {
    if (cancel) onChange(original.current);
    dialog.current?.close();
    setOpen(false);
    trigger.current?.focus();
  }
  function change(next: HSV) {
    setHSV(next);
    const value = hsvToHex(next);
    setHex(value);
    onChange(value);
  }
  function point(event: PointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect(),
      x = event.clientX - bounds.left - bounds.width / 2,
      y = event.clientY - bounds.top - bounds.height / 2;
    change({
      ...hsv,
      h: ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360,
      s: Math.min(100, (Math.hypot(x, y) / (bounds.width / 2)) * 100),
    });
  }
  return (
    <>
      <button
        type="button"
        className="custom-color-trigger"
        aria-label={t("Choose custom color")}
        title={t("Choose custom color")}
        disabled={disabled}
        onClick={begin}
        ref={trigger}
      >
        <Palette size={15} />
      </button>
      {open &&
        createPortal(
          <dialog
            className="color-wheel-dialog"
            ref={dialog}
            aria-labelledby={id + "-title"}
            onCancel={() => {
              onChange(original.current);
              setOpen(false);
              trigger.current?.focus();
            }}
          >
            <header>
              <h2 id={id + "-title"}>{t("Choose custom color")}</h2>
              <button
                type="button"
                aria-label={t("Close")}
                onClick={() => close(true)}
              >
                <X size={18} />
              </button>
            </header>
            <div className="color-wheel-content">
              <div
                className="color-wheel-surface"
                role="group"
                aria-label={t("Color wheel")}
                aria-describedby={id + "-help"}
                onPointerDown={(event) => {
                  event.preventDefault();
                  event.currentTarget.setPointerCapture(event.pointerId);
                  point(event);
                }}
                onPointerMove={(event) => {
                  if (event.currentTarget.hasPointerCapture(event.pointerId))
                    point(event);
                }}
              >
                <span
                  className="color-wheel-shade"
                  style={{ opacity: 1 - hsv.v / 100 }}
                />
                <span
                  className="color-wheel-marker"
                  style={{
                    left: `${50 + (Math.cos((hsv.h * Math.PI) / 180) * hsv.s) / 2}%`,
                    top: `${50 + (Math.sin((hsv.h * Math.PI) / 180) * hsv.s) / 2}%`,
                  }}
                />
              </div>
              <p id={id + "-help"}>
                {t("Use the wheel or the sliders to choose any color.")}
              </p>
              {(
                [
                  ["h", "Hue", 360],
                  ["s", "Saturation", 100],
                  ["v", "Brightness", 100],
                ] as const
              ).map(([key, label, max]) => (
                <label className="color-wheel-slider" key={key}>
                  <span>
                    {t(label)}
                    <output>
                      {Math.round(hsv[key])}
                      {key === "h" ? "\u00b0" : "%"}
                    </output>
                  </span>
                  <input
                    type="range"
                    min={0}
                    max={max}
                    step={1}
                    aria-label={t(label)}
                    value={Math.round(hsv[key])}
                    onChange={(event) =>
                      change({ ...hsv, [key]: Number(event.target.value) })
                    }
                  />
                </label>
              ))}
              <label className="color-wheel-hex">
                <span
                  style={{ backgroundColor: hsvToHex(hsv) }}
                  aria-hidden="true"
                />
                <span>
                  {t("Hex color")}
                  <input
                    type="text"
                    aria-label={t("Hex color")}
                    value={hex}
                    spellCheck={false}
                    maxLength={7}
                    aria-invalid={!isHexColor(hex)}
                    onChange={(event) => {
                      const value = event.target.value;
                      setHex(value);
                      if (isHexColor(value)) {
                        setHSV(hexToHSV(value));
                        onChange(value.toLowerCase());
                      }
                    }}
                  />
                </span>
              </label>
            </div>
            <footer>
              <button type="button" onClick={() => close(true)}>
                {t("Cancel")}
              </button>
              <button
                type="button"
                className="primary"
                disabled={!isHexColor(hex)}
                onClick={() => close()}
              >
                {t("Done")}
              </button>
            </footer>
          </dialog>,
          document.body,
        )}
    </>
  );
}
