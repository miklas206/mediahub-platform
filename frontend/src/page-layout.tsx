import { t } from "./i18n";
import {
  Children,
  createContext,
  isValidElement,
  useContext,
  useCallback,
  useEffect,
  useState,
  type ReactNode,
  type ReactElement,
  type CSSProperties,
} from "react";
import {
  ArrowDown,
  ArrowUp,
  GripVertical,
  LayoutGrid,
  RotateCcw,
  X,
} from "lucide-react";
import "./page-layout.css";

type Layouts = Record<string, string[]>;
type Geometry = { columns: number; widths: Record<string, number> };
export function readGeometry(raw: string | null): Geometry {
  try {
    const value = JSON.parse(raw || "{}");
    const columns = [0, 1, 2, 3].includes(value?.columns) ? value.columns : 0;
    const widths =
      value?.widths &&
      typeof value.widths === "object" &&
      !Array.isArray(value.widths)
        ? Object.fromEntries(
            Object.entries(value.widths).filter(
              ([key, width]) =>
                key.length < 1000 &&
                typeof width === "number" &&
                [0, 1, 2, 3].includes(width),
            ),
          )
        : {};
    return { columns, widths: widths as Record<string, number> };
  } catch {
    return { columns: 0, widths: {} };
  }
}
type LayoutContext = {
  hidden: Layouts;
  hide: (group: string, items: string[]) => void;
  register: (group: string, cards: CardChoice[]) => () => void;
  geometry: Geometry;
  resize: (group: string, item: string, width: number) => void;
  editing: boolean;
  layouts: Layouts;
  save: (group: string, order: string[]) => void;
};
type CardChoice = { id: string; title: string; defaultHidden: boolean };
const Context = createContext<LayoutContext | null>(null);
const dragType = "application/x-mediahub-layout";

export function readLayouts(raw: string | null): Layouts {
  try {
    const value: unknown = JSON.parse(raw || "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return Object.fromEntries(
      Object.entries(value).filter(
        ([, order]) =>
          Array.isArray(order) &&
          order.length <= 500 &&
          order.every((id) => typeof id === "string" && id.length < 500),
      ),
    );
  } catch {
    return {};
  }
}

export function orderedIds(current: string[], saved: string[] = []) {
  return [
    ...new Set([...saved.filter((id) => current.includes(id)), ...current]),
  ];
}

export function PageLayout({
  storageKey,
  children,
}: {
  storageKey: string;
  children: ReactNode;
}) {
  const key = `mediahub.layout.v1:${storageKey}`;
  const [editing, setEditing] = useState(false);
  const [layouts, setLayouts] = useState<Layouts>(() => {
    try {
      return readLayouts(localStorage.getItem(key));
    } catch {
      return {};
    }
  });
  const geometryKey = `mediahub.layout.size.v1:${storageKey}`;
  const [geometry, setGeometry] = useState<Geometry>(() => {
    try {
      return readGeometry(localStorage.getItem(geometryKey));
    } catch {
      return readGeometry(null);
    }
  });
  function persistGeometry(next: Geometry) {
    setGeometry(next);
    try {
      localStorage.setItem(geometryKey, JSON.stringify(next));
      setMessage(t("Layout saved in this browser."));
    } catch {
      setMessage(
        t(
          "Layout changed, but this browser could not save it. It will reset when you reload.",
        ),
      );
    }
  }
  const [message, setMessage] = useState("");
  const visibilityKey = `mediahub.layout.hidden.v1:${storageKey}`;
  const [hidden, setHidden] = useState<Layouts>(() => {
    try {
      return readLayouts(localStorage.getItem(visibilityKey));
    } catch {
      return {};
    }
  });
  const [groups, setGroups] = useState<Record<string, CardChoice[]>>({});
  const register = useCallback((group: string, cards: CardChoice[]) => {
    setGroups((current) => ({ ...current, [group]: cards }));
    return () =>
      setGroups((current) => {
        const next = { ...current };
        delete next[group];
        return next;
      });
  }, []);
  function persistHidden(next: Layouts) {
    setHidden(next);
    try {
      localStorage.setItem(visibilityKey, JSON.stringify(next));
      setMessage(t("Layout saved in this browser."));
    } catch {
      setMessage(
        t(
          "Layout changed, but this browser could not save it. It will reset when you reload.",
        ),
      );
    }
  }
  function persist(next: Layouts) {
    setLayouts(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
      setMessage(t("Layout saved in this browser."));
    } catch {
      setMessage(
        t(
          "Layout changed, but this browser could not save it. It will reset when you reload.",
        ),
      );
    }
  }
  return (
    <Context.Provider
      value={{
        hidden,
        hide: (group, items) => persistHidden({ ...hidden, [group]: items }),
        register,
        editing,
        geometry,
        resize: (group, item, width) =>
          persistGeometry({
            ...geometry,
            widths: { ...geometry.widths, [`${group}:${item}`]: width },
          }),
        layouts,
        save: (group, order) => persist({ ...layouts, [group]: order }),
      }}
    >
      <div className="layout-toolbar">
        <button
          type="button"
          aria-pressed={editing}
          onClick={() => setEditing(!editing)}
        >
          <LayoutGrid size={16} />{" "}
          {editing ? t("Done arranging") : t("Customize layout")}
        </button>
        {editing && (
          <>
            <span>
              {t(
                "Drag anywhere on a card, or use the arrows. Saved per page in this browser.",
              )}
            </span>
            <label className="layout-columns">
              {t("Columns")}
              <select
                aria-label={t("Columns")}
                value={geometry.columns}
                onChange={(event) =>
                  persistGeometry({
                    ...geometry,
                    columns: Number(event.target.value),
                  })
                }
              >
                <option value={0}>{t("Original layout")}</option>
                {[1, 2, 3].map((count) => (
                  <option key={count} value={count}>
                    {t("{count} columns", { count })}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => {
                persist({});
                persistGeometry({ columns: 0, widths: {} });
                persistHidden({});
              }}
            >
              <RotateCcw size={15} />
              {t(" Reset this page")}
            </button>
            <details className="layout-card-picker">
              <summary>{t("Choose cards")}</summary>
              <div>
                {Object.entries(groups).flatMap(([group, cards]) =>
                  cards.map((card) => (
                    <label key={`${group}:${card.id}`}>
                      <input
                        type="checkbox"
                        checked={
                          !(
                            hidden[group] ||
                            cards
                              .filter((c) => c.defaultHidden)
                              .map((c) => c.id)
                          ).includes(card.id)
                        }
                        onChange={(event) => {
                          const current =
                            hidden[group] ||
                            cards
                              .filter((c) => c.defaultHidden)
                              .map((c) => c.id);
                          persistHidden({
                            ...hidden,
                            [group]: event.target.checked
                              ? current.filter((id) => id !== card.id)
                              : [...current, card.id],
                          });
                        }}
                      />
                      {t(card.title)}
                    </label>
                  )),
                )}
              </div>
            </details>
          </>
        )}
        <span className="layout-save-status" role="status">
          {message}
        </span>
      </div>
      {children}
    </Context.Provider>
  );
}

export function canMove(
  node: ReactNode,
): node is ReactElement<Record<string, unknown>> {
  if (!isValidElement<Record<string, unknown>>(node)) return false;
  if (
    "error" in node.props ||
    node.props.role === "alert" ||
    node.props.role === "status"
  )
    return false;
  if (node.props["data-layout-fixed"]) return false;
  if (typeof node.type !== "string") {
    // Page components and nested layout groups contain their own cards and fixed headings.
    return typeof node.props.title === "string";
  }
  return (
    ["div", "section", "article", "details", "form"].includes(node.type) &&
    /panel|card|overview|store-callout|seedbox-client-summary/.test(
      String(node.props.className || ""),
    ) &&
    !/notice|success|skeleton|tabs|toolbar|button-row/.test(
      String(node.props.className || ""),
    )
  );
}

function cardTitle(node: ReactNode): string {
  if (!isValidElement<Record<string, unknown>>(node)) return "";
  if (typeof node.props["data-layout-title"] === "string")
    return node.props["data-layout-title"];
  if (typeof node.props.title === "string") return node.props.title;
  if (typeof node.type === "string" && /^(h[123]|strong)$/.test(node.type))
    return Children.toArray(node.props.children as ReactNode)
      .filter((c) => typeof c === "string" || typeof c === "number")
      .join("");
  const nested = Children.toArray(node.props.children as ReactNode)
    .map(cardTitle)
    .find(Boolean);
  if (nested) return nested;
  return "";
}

export function LayoutGroup({
  id,
  className = "stack",
  children,
  resizable = false,
  wideFirst = false,
  defaultHidden = [],
}: {
  id: string;
  className?: string;
  resizable?: boolean;
  wideFirst?: boolean;
  defaultHidden?: string[];
  children: ReactNode;
}) {
  const context = useContext(Context);
  const nodes = Children.toArray(children);
  const movable = nodes.filter(canMove);
  const byId = new Map(movable.map((node) => [String(node.key), node]));
  const ids = orderedIds([...byId.keys()], context?.layouts[id]);
  const choices = JSON.stringify(
    movable.map((item, index) => ({
      id: String(item.key),
      title: cardTitle(item) || t("Box {count}", { count: index + 1 }),
      defaultHidden: defaultHidden.includes(
        String(item.key).replace(/^\.\$/, ""),
      ),
    })),
  );
  const register = context?.register;
  useEffect(() => register?.(id, JSON.parse(choices)), [id, choices, register]);
  const hidden =
    context?.hidden[id] ||
    (JSON.parse(choices) as CardChoice[])
      .filter((c) => c.defaultHidden)
      .map((c) => c.id);
  const visibleIds = ids.filter((item) => !hidden.includes(item));
  const [announcement, setAnnouncement] = useState("");
  function move(source: string, target: string) {
    if (
      !context ||
      source === target ||
      !visibleIds.includes(source) ||
      !visibleIds.includes(target)
    )
      return;
    const next = visibleIds.filter((item) => item !== source);
    next.splice(visibleIds.indexOf(target), 0, source);
    // Keep unavailable cards in the preference so a temporary loading state does not erase them.
    context.save(id, [
      ...next,
      ...orderedIds(ids, context.layouts[id]).filter(
        (item) => !next.includes(item),
      ),
      ...(context.layouts[id] || []).filter((item) => !ids.includes(item)),
    ]);
    setAnnouncement(
      t("Box moved to position {position} of {count}.", {
        position: next.indexOf(source) + 1,
        count: visibleIds.length,
      }),
    );
  }
  const columns = resizable ? context?.geometry.columns || 0 : 0;
  let cursor = 0;
  return (
    <div
      className={`${className} layout-group ${columns ? "layout-custom-grid" : ""}`}
      style={
        columns ? ({ "--layout-columns": columns } as CSSProperties) : undefined
      }
    >
      {nodes.map((node) => {
        if (!canMove(node)) return node;
        const itemId = ids[cursor++];
        if (hidden.includes(itemId)) return null;
        const item = byId.get(itemId)!;
        const index = visibleIds.indexOf(itemId);
        return (
          <LayoutItem
            key={itemId}
            item={item}
            editing={!!context?.editing}
            title={cardTitle(item) || t("Box {count}", { count: index + 1 })}
            hide={() => context?.hide(id, [...hidden, itemId])}
            columns={columns}
            width={
              context?.geometry.widths[`${id}:${itemId}`] ??
              (wideFirst && itemId === String(movable[0]?.key) ? 0 : 1)
            }
            resize={
              resizable && columns
                ? (width) => context?.resize(id, itemId, width)
                : undefined
            }
            group={id}
            itemId={itemId}
            index={index}
            count={visibleIds.length}
            moveBy={(delta) => move(itemId, visibleIds[index + delta])}
            onDrop={(source) => move(source, itemId)}
          />
        );
      })}
      <span className="layout-announcement" role="status">
        {announcement}
      </span>
    </div>
  );
}

function LayoutItem({
  item,
  editing,
  group,
  itemId,
  index,
  count,
  moveBy,
  onDrop,
  columns,
  width,
  resize,
  title,
  hide,
}: {
  item: ReactElement<Record<string, unknown>>;
  editing: boolean;
  group: string;
  itemId: string;
  index: number;
  count: number;
  columns: number;
  width: number;
  resize?: (width: number) => void;
  title: string;
  hide: () => void;
  moveBy: (delta: number) => void;
  onDrop: (source: string) => void;
}) {
  const [over, setOver] = useState(false);
  return (
    <div
      className={`layout-item ${editing ? "is-arranging" : ""} ${over ? "is-drop-target" : ""}`}
      style={
        columns
          ? ({
              "--layout-span": width === 0 ? columns : Math.min(width, columns),
            } as CSSProperties)
          : undefined
      }
      data-layout-item={itemId}
      data-layout-title={title}
      onDragOver={(event) => {
        if (editing && event.dataTransfer.types.includes(dragType)) {
          event.preventDefault();
          event.stopPropagation();
          setOver(true);
        }
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        if (!editing || !event.dataTransfer.types.includes(dragType)) return;
        event.preventDefault();
        event.stopPropagation();
        setOver(false);
        try {
          const data = JSON.parse(event.dataTransfer.getData(dragType));
          if (data.group === group && typeof data.id === "string")
            onDrop(data.id);
        } catch {
          /* Ignore unrelated or malformed drags. */
        }
      }}
    >
      {editing && (
        <>
          <button
            type="button"
            className="layout-drag-surface"
            draggable
            aria-label={t("Move {title}", { title: t(title) })}
            title={t("Drag to move, or use the arrow keys")}
            onDragStart={(event) => {
              event.stopPropagation();
              event.dataTransfer.effectAllowed = "move";
              event.dataTransfer.setData(
                dragType,
                JSON.stringify({ group, id: itemId }),
              );
            }}
            onKeyDown={(event) => {
              const delta = ["ArrowUp", "ArrowLeft"].includes(event.key)
                ? -1
                : ["ArrowDown", "ArrowRight"].includes(event.key)
                  ? 1
                  : 0;
              if (delta) {
                event.preventDefault();
                if (index + delta >= 0 && index + delta < count) moveBy(delta);
              }
            }}
          >
            <GripVertical size={17} aria-hidden="true" />
          </button>
          <div className="layout-item-tools">
            {resize && (
              <label className="layout-width">
                {t("Width")}
                <select
                  aria-label={t("Width of {title}", { title })}
                  value={width}
                  onChange={(event) => resize(Number(event.target.value))}
                >
                  <option value={0}>{t("Full row")}</option>
                  {[1, 2, 3].map((span) => (
                    <option key={span} value={span}>
                      {t("{count} columns", { count: span })}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <button
              type="button"
              aria-label={t("Move {title} earlier", { title: t(title) })}
              disabled={index === 0}
              onClick={() => moveBy(-1)}
            >
              <ArrowUp size={16} />
            </button>
            <button
              type="button"
              aria-label={t("Move {title} later", { title: t(title) })}
              disabled={index === count - 1}
              onClick={() => moveBy(1)}
            >
              <ArrowDown size={16} />
            </button>
            <button
              type="button"
              aria-label={t("Hide {title}", { title: t(title) })}
              title={t("Hide card")}
              onClick={hide}
            >
              <X size={16} />
            </button>
          </div>
        </>
      )}
      <div className="layout-item-content" inert={editing}>
        {item}
      </div>
    </div>
  );
}
