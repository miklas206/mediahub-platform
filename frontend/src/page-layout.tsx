import { translateText, t } from "./i18n";

import {
  Children,
  createContext,
  isValidElement,
  useContext,
  useCallback,
  useEffect,
  useState,
  useRef,
  useLayoutEffect,
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
import {
  gridPosition,
  placeGridCard,
  type GridPosition,
  type GridCard,
} from "./layout-grid";
import { useLayoutPointer } from "./layout-pointer";

type Layouts = Record<string, string[]>;
type Geometry = {
  columns: number;
  widths: Record<string, number>;
  heights: Record<string, number>;
  positions?: Record<string, GridPosition>;
};
const widthPercentages = [25, 33, 42, 50, 58, 67, 75, 83, 92, 100];
export function snapCardWidth(pixels: number, gridWidth: number, gap = 16) {
  const span = Math.max(
    3,
    Math.min(12, Math.round((pixels + gap) / ((gridWidth + gap) / 12))),
  );
  return Math.round((span * 100) / 12);
}
export function snapCardHeight(pixels: number) {
  return Math.max(144, Math.min(2400, Math.round(pixels / 24) * 24));
}
export function cardWidthPercentage(width: number, columns: number) {
  // Older preferences store a column span. Keep the same visual width on upgrade.
  if (width === 0) return 100;
  if (width <= 3 && width > 0)
    return Math.round((Math.min(width, columns || 3) / (columns || 3)) * 100);
  return width;
}
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
                [0, 1, 2, 3, ...widthPercentages].includes(width),
            ),
          )
        : {};
    const heights =
      value?.heights &&
      typeof value.heights === "object" &&
      !Array.isArray(value.heights)
        ? Object.fromEntries(
            Object.entries(value.heights).filter(
              ([key, height]) =>
                key.length < 1000 &&
                typeof height === "number" &&
                Number.isInteger(height) &&
                height >= 144 &&
                height <= 2400 &&
                height % 24 === 0,
            ),
          )
        : {};
    return {
      columns,
      widths: widths as Record<string, number>,
      heights: heights as Record<string, number>,
      ...(value?.positions &&
      typeof value.positions === "object" &&
      !Array.isArray(value.positions)
        ? {
            positions: Object.fromEntries(
              Object.entries(value.positions).filter(([key, position]) => {
                const p = position as GridPosition | null;
                return (
                  key.length < 1000 &&
                  p &&
                  Number.isInteger(p.column) &&
                  p.column >= 1 &&
                  p.column <= 12 &&
                  Number.isInteger(p.row) &&
                  p.row >= 1 &&
                  p.row <= 2000
                );
              }),
            ) as Record<string, GridPosition>,
          }
        : {}),
    };
  } catch {
    return { columns: 0, widths: {}, heights: {} };
  }
}
type LayoutContext = {
  hidden: Layouts;
  hide: (group: string, items: string[]) => void;
  register: (group: string, cards: CardChoice[]) => void;
  unregister: (group: string) => void;
  geometry: Geometry;
  resize: (group: string, item: string, width: number) => void;
  resizeCard: (
    group: string,
    item: string,
    size: { width?: number; height?: number },
    aliasKey?: string,
  ) => void;
  editing: boolean;
  layouts: Layouts;
  save: (group: string, order: string[], keepPositions?: boolean) => void;
  place: (group: string, cards: GridCard[]) => void;
};
type CardChoice = { id: string; title: string; defaultHidden: boolean };
const Context = createContext<LayoutContext | null>(null);

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

const vpnCardKeys = [
  ["runtime-SeedboxPanel-1", ".0", ".0:0"],
  ["seedbox-daily-location", ".0", ".$vpn-location"],
];
export function migrateVPNLayouts(layouts: Layouts): Layouts {
  if (
    layouts["seedbox-vpn-cards"] ||
    !vpnCardKeys.some(([group]) => layouts[group])
  )
    return layouts;
  return {
    ...layouts,
    "seedbox-vpn-cards": vpnCardKeys.flatMap(([group, oldId, newId]) =>
      (layouts[group] || []).includes(oldId) ? [newId] : [],
    ),
  };
}
export function migrateVPNGeometry(geometry: Geometry): Geometry {
  const widths = { ...geometry.widths };
  const heights = { ...geometry.heights };
  for (const [group, oldId, newId] of vpnCardKeys) {
    const previous = `${group}:${oldId}`;
    const next = `seedbox-vpn-cards:${newId}`;
    if (widths[next] === undefined && widths[previous] !== undefined)
      widths[next] = widths[previous];
    if (heights[next] === undefined && heights[previous] !== undefined)
      heights[next] = heights[previous];
  }
  return { ...geometry, widths, heights };
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
      return migrateVPNLayouts(readLayouts(localStorage.getItem(key)));
    } catch {
      return {};
    }
  });
  const geometryKey = `mediahub.layout.size.v1:${storageKey}`;
  const [geometry, setGeometry] = useState<Geometry>(() => {
    try {
      return migrateVPNGeometry(
        readGeometry(localStorage.getItem(geometryKey)),
      );
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
      return migrateVPNLayouts(
        readLayouts(localStorage.getItem(visibilityKey)),
      );
    } catch {
      return {};
    }
  });
  const [groups, setGroups] = useState<Record<string, CardChoice[]>>({});
  const register = useCallback((group: string, cards: CardChoice[]) => {
    setGroups((current) => ({ ...current, [group]: cards }));
  }, []);
  const unregister = useCallback((group: string) => {
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
        unregister,
        editing,
        geometry,
        resize: (group, item, width) => {
          const widths = { ...geometry.widths };
          if (width === -1) delete widths[`${group}:${item}`];
          else widths[`${group}:${item}`] = width;
          persistGeometry({
            ...geometry,
            widths,
          });
        },
        resizeCard: (group, item, size, aliasKey) => {
          const key = `${group}:${item}`;
          const widths = { ...geometry.widths };
          const heights = { ...geometry.heights };
          for (const address of new Set([key, aliasKey || key])) {
            if (size.width === -1) delete widths[address];
            else if (size.width !== undefined) widths[address] = size.width;
            if (size.height === -1) delete heights[address];
            else if (size.height !== undefined) heights[address] = size.height;
          }
          persistGeometry({ ...geometry, widths, heights });
        },
        layouts,
        save: (group, order, keepPositions) => {
          const positions = Object.fromEntries(
            Object.entries(geometry.positions || {}).filter(
              ([key]) => !key.startsWith(`${group}:`),
            ),
          );
          if (!keepPositions) persistGeometry({ ...geometry, positions });
          persist({ ...layouts, [group]: order });
        },
        place: (group, cards) => {
          const positions = { ...geometry.positions };
          const widths = { ...geometry.widths };
          for (const card of cards)
            positions[`${group}:${card.id}`] = {
              column: card.column,
              row: card.row,
            };
          for (const card of cards)
            widths[`${group}:${card.id}`] = Math.round(
              (card.columns * 100) / 12,
            );
          persistGeometry({ ...geometry, positions, widths });
          persist({ ...layouts, [group]: cards.map((card) => card.id) });
        },
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
                "Drag cards to move them. Pull an edge or corner to resize on the grid.",
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
                persistGeometry({ columns: 0, widths: {}, heights: {} });
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
          {translateText(message)}
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

type LayoutEntry = {
  node: ReactNode;
  id: string;
  sourceGroup: string;
  sourceId: string;
  span?: number;
  defaultHidden?: boolean;
};

// Nested grids are presentation, not movement boundaries. Keep each card's
// previous storage address so existing widths and hidden choices still work.
function layoutEntries(
  children: ReactNode,
  group: string,
  context: LayoutContext | null,
  nested = false,
  options: {
    className?: string;
    wideFirst?: boolean;
    fullWidth?: string[];
    defaultHidden?: string[];
  } = {},
): LayoutEntry[] {
  const nodes = Children.toArray(children);
  const movable = nodes.filter(canMove);
  const byId = new Map(movable.map((node) => [String(node.key), node]));
  const order = orderedIds([...byId.keys()], context?.layouts[group]);
  let cursor = 0;
  return nodes.flatMap((original) => {
    const node = canMove(original) ? byId.get(order[cursor++])! : original;
    if (isValidElement(node) && node.type === LayoutGroup) {
      const props = node.props as {
        id: string;
        children: ReactNode;
      } & typeof options;
      return layoutEntries(props.children, props.id, context, true, props);
    }
    const sourceId = isValidElement(node) ? String(node.key) : "";
    const plainId = sourceId.replace(/^\.\$/, "");
    const full =
      options.fullWidth?.includes(plainId) ||
      (options.wideFirst && sourceId === String(movable[0]?.key));
    const sourceHidden = context?.hidden[group];
    return [
      {
        node,
        id: nested ? `${group}/${sourceId}` : sourceId,
        sourceId,
        sourceGroup: group,
        span: full
          ? 12
          : nested
            ? /updates-grid/.test(options.className || "")
              ? 12
              : /apps-grid/.test(options.className || "")
                ? 12 /
                  Math.min(
                    /store-grid/.test(options.className || "") ? 4 : 3,
                    Math.max(1, movable.length),
                  )
                : /runtime-panels|security-grid|torrent-panels|windows-share-grid/.test(
                      options.className || "",
                    )
                  ? 6
                  : 12
            : undefined,
        defaultHidden: sourceHidden
          ? sourceHidden.includes(sourceId)
          : options.defaultHidden?.includes(plainId),
      },
    ];
  });
}

export function LayoutGroup({
  id,
  className = "stack",
  children,
  wideFirst = false,
  defaultHidden = [],
  fullWidth = [],
}: {
  id: string;
  className?: string;
  wideFirst?: boolean;
  defaultHidden?: string[];
  fullWidth?: string[];
  children: ReactNode;
}) {
  const context = useContext(Context);
  const entries = layoutEntries(children, id, context, false, {
    className,
    wideFirst,
    defaultHidden,
    fullWidth,
  });
  const nodes = entries.map((entry) => entry.node);
  const movable = nodes.filter(canMove);
  const metadata = new Map(
    entries
      .filter((entry) => canMove(entry.node))
      .map((entry) => [entry.id, entry]),
  );
  const byId = new Map(
    [...metadata].map(([key, entry]) => [
      key,
      entry.node as ReactElement<Record<string, unknown>>,
    ]),
  );
  const ids = orderedIds([...byId.keys()], context?.layouts[id]);
  const choices = JSON.stringify(
    [...metadata].map(([key, entry], index) => ({
      id: key,
      title: cardTitle(entry.node) || t("Box {count}", { count: index + 1 }),
      defaultHidden: !!entry.defaultHidden,
    })),
  );
  const register = context?.register;
  const unregister = context?.unregister;
  // Choice updates must retain group insertion order and the picker's DOM nodes.
  useEffect(() => register?.(id, JSON.parse(choices)), [id, choices, register]);
  useEffect(() => () => unregister?.(id), [id, unregister]);
  const hidden =
    context?.hidden[id] ||
    (JSON.parse(choices) as CardChoice[])
      .filter((c) => c.defaultHidden)
      .map((c) => c.id);
  const visibleIds = ids.filter((item) => !hidden.includes(item));
  const gridElement = useRef<HTMLDivElement>(null);
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
  function measureCards(): GridCard[] {
    const grid = gridElement.current;
    if (!grid) return [];
    const bounds = grid.getBoundingClientRect();
    return [
      ...grid.querySelectorAll<HTMLDivElement>(":scope > .layout-item"),
    ].map((node) => {
      const card = node.getBoundingClientRect();
      const columns = Math.max(
        3,
        Math.min(
          12,
          Math.round((card.width + 16) / ((bounds.width + 16) / 12)),
        ),
      );
      return {
        id: node.dataset.layoutItem!,
        columns,
        rows: Math.ceil((card.height + 16) / 24),
        ...gridPosition(
          card.left - bounds.left,
          card.top - bounds.top,
          bounds.width,
          columns,
        ),
      };
    });
  }
  function place(item: string, position: GridPosition) {
    if (!context) return;
    const cards = measureCards();
    if (window.matchMedia("(max-width: 760px)").matches) {
      const order = placeGridCard(
        cards.map((card) => ({ ...card, column: 1, columns: 12 })),
        item,
        { ...position, column: 1 },
      );
      context.save(
        id,
        order.map((card) => card.id),
        true,
      );
    } else context.place(id, placeGridCard(cards, item, position));
    setAnnouncement(t("Card placed at column {column}, row {row}.", position));
  }
  useEffect(() => {
    const grid = gridElement.current;
    if (!grid || !context || window.matchMedia("(max-width: 760px)").matches)
      return;
    function sizeChanged(event: Event) {
      const item = (event as CustomEvent<string>).detail;
      if (!context?.geometry.positions?.[`${id}:${item}`]) return;
      if (grid!.querySelector(".is-resizing")) return;
      const cards = measureCards();
      const current = cards.find((card) => card.id === item);
      if (!current) return;
      const next = placeGridCard(cards, item, current);
      if (
        next.some((card) => {
          const saved = context.geometry.positions?.[`${id}:${card.id}`];
          return saved?.column !== card.column || saved?.row !== card.row;
        })
      )
        context.place(id, next);
    }
    grid.addEventListener("mediahub-layout-size", sizeChanged);
    return () => grid.removeEventListener("mediahub-layout-size", sizeChanged);
  });
  const columns = context?.geometry.columns || 0;
  const customGrid =
    movable.length > 0 &&
    (entries.some((entry) => entry.sourceGroup !== id) ||
      fullWidth.length > 0 ||
      columns > 0 ||
      ids.some(
        (item) =>
          context?.geometry.widths[`${id}:${item}`] !== undefined ||
          context?.geometry.heights[`${id}:${item}`] !== undefined ||
          context?.geometry.positions?.[`${id}:${item}`] !== undefined,
      ));
  let cursor = 0;
  return (
    <div className="layout-section">
      {nodes.filter((node) => !canMove(node))}
      <div
        ref={gridElement}
        data-layout-group={id}
        className={`${className} layout-group ${context?.editing ? "is-editing-grid" : ""} ${customGrid ? "layout-custom-grid" : ""} ${customGrid && !columns ? "layout-auto-grid" : ""}`}
        style={
          columns
            ? ({ "--layout-default-span": 12 / columns } as CSSProperties)
            : undefined
        }
      >
        {nodes.filter(canMove).map(() => {
          const itemId = ids[cursor++];
          if (hidden.includes(itemId)) return null;
          const item = byId.get(itemId)!;
          const entry = metadata.get(itemId)!;
          const previousKey = `${entry.sourceGroup}:${entry.sourceId}`;
          const index = visibleIds.indexOf(itemId);
          return (
            <LayoutItem
              key={itemId}
              item={item}
              editing={!!context?.editing && !item.props["data-layout-nested"]}
              title={cardTitle(item) || t("Box {count}", { count: index + 1 })}
              hide={() => context?.hide(id, [...hidden, itemId])}
              columns={columns}
              defaultSpan={columns ? undefined : entry.span}
              defaultFullWidth={fullWidth.includes(itemId.replace(/^\.\$/, ""))}
              width={
                context?.geometry.widths[`${id}:${itemId}`] ??
                context?.geometry.widths[previousKey] ??
                (wideFirst && itemId === String(movable[0]?.key) ? 0 : -1)
              }
              height={
                context?.geometry.heights[`${id}:${itemId}`] ??
                context?.geometry.heights[previousKey]
              }
              resizeCard={
                context
                  ? (size) =>
                      context.resizeCard(
                        entry.sourceGroup,
                        entry.sourceId,
                        size,
                        `${id}:${itemId}`,
                      )
                  : undefined
              }
              resize={
                context
                  ? (width) =>
                      context?.resizeCard(
                        entry.sourceGroup,
                        entry.sourceId,
                        { width },
                        `${id}:${itemId}`,
                      )
                  : undefined
              }
              itemId={itemId}
              index={index}
              count={visibleIds.length}
              moveBy={(delta) => move(itemId, visibleIds[index + delta])}
              position={context?.geometry.positions?.[`${id}:${itemId}`]}
              place={(position) => place(itemId, position)}
            />
          );
        })}
        <div className="layout-grid-guides" aria-hidden="true">
          {Array.from({ length: 12 }, (_, column) => (
            <span key={column} />
          ))}
        </div>
        <span className="layout-announcement" role="status">
          {announcement}
        </span>
      </div>
    </div>
  );
}

function LayoutItem({
  item,
  editing,
  itemId,
  index,
  count,
  moveBy,
  position,
  place,
  columns,
  width,
  resize,
  title,
  hide,
  height,
  resizeCard,
  defaultFullWidth,
  defaultSpan,
}: {
  item: ReactElement<Record<string, unknown>>;
  editing: boolean;
  itemId: string;
  index: number;
  count: number;
  columns: number;
  width: number;
  height?: number;
  defaultFullWidth?: boolean;
  defaultSpan?: number;
  resizeCard?: (size: { width?: number; height?: number }) => void;
  resize?: (width: number) => void;
  title: string;
  hide: () => void;
  moveBy: (delta: number) => void;
  position?: GridPosition;
  place: (position: GridPosition) => void;
}) {
  const element = useRef<HTMLDivElement>(null);
  const pointer = useLayoutPointer(element, place);
  const [rowSpan, setRowSpan] = useState(1);
  useLayoutEffect(() => {
    const node = element.current;
    if (!node) return;
    setRowSpan(Math.ceil((node.getBoundingClientRect().height + 16) / 24));
    const observer = new ResizeObserver(() => {
      setRowSpan(Math.ceil((node.getBoundingClientRect().height + 16) / 24));
      node.dispatchEvent(
        new CustomEvent("mediahub-layout-size", {
          bubbles: true,
          detail: itemId,
        }),
      );
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [itemId, editing, width, height, columns, defaultFullWidth, defaultSpan]);
  const [draft, setDraft] = useState<{
    width?: number;
    height?: number;
  } | null>(null);
  const gesture = useRef<{
    pointer: number;
    x: number;
    y: number;
    width: number;
    height: number;
    grid: number;
    gap: number;
    direction: string;
    size: { width?: number; height?: number };
  } | null>(null);
  const displayWidth = draft?.width ?? width;
  const displayHeight = draft?.height ?? height;
  return (
    <div
      ref={element}
      className={`layout-item ${displayWidth === -1 ? "is-default-width" : ""} ${editing ? "is-arranging" : ""} ${draft ? "is-resizing" : ""} ${displayHeight ? "has-custom-height" : ""} ${pointer.dragging ? "is-pointer-dragging" : ""}`}
      style={
        {
          "--layout-row-span": rowSpan,
          ...(position
            ? {
                "--layout-column": Math.min(
                  position.column,
                  13 -
                    (displayWidth !== -1
                      ? Math.round(
                          (cardWidthPercentage(displayWidth, columns) * 12) /
                            100,
                        )
                      : defaultFullWidth
                        ? 12
                        : defaultSpan || 6),
                ),
                "--layout-row": position.row,
              }
            : {}),
          ...(defaultFullWidth || defaultSpan
            ? { "--layout-default-span": defaultFullWidth ? 12 : defaultSpan }
            : {}),
          ...(displayWidth !== -1
            ? {
                "--layout-span": Math.round(
                  (cardWidthPercentage(displayWidth, columns) * 12) / 100,
                ),
              }
            : {}),
          ...(displayHeight ? { "--layout-height": `${displayHeight}px` } : {}),
        } as CSSProperties
      }
      data-layout-item={itemId}
      data-layout-title={title}
      data-layout-positioned={position ? "true" : undefined}
    >
      {editing && (
        <>
          <button
            type="button"
            className="layout-drag-surface"
            onPointerDown={pointer.start}
            aria-label={t("Move {title}", { title: t(title) })}
            title={t("Drag to move, or use the arrow keys")}
            onKeyDown={(event) => {
              if (
                event.altKey &&
                ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(
                  event.key,
                ) &&
                element.current?.parentElement
              ) {
                event.preventDefault();
                const bounds = element.current.getBoundingClientRect();
                const grid =
                  element.current.parentElement.getBoundingClientRect();
                const columns = Math.max(
                  3,
                  Math.round((bounds.width + 16) / ((grid.width + 16) / 12)),
                );
                const current = gridPosition(
                  bounds.left - grid.left,
                  bounds.top - grid.top,
                  grid.width,
                  columns,
                );
                place({
                  column:
                    current.column +
                    (event.key === "ArrowRight"
                      ? 1
                      : event.key === "ArrowLeft"
                        ? -1
                        : 0),
                  row:
                    current.row +
                    (event.key === "ArrowDown"
                      ? 1
                      : event.key === "ArrowUp"
                        ? -1
                        : 0),
                });
                return;
              }
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
            {height && (
              <button
                type="button"
                aria-label={t("Restore automatic height for {title}", {
                  title,
                })}
                title={t("Automatic height")}
                onClick={() => resizeCard?.({ height: -1 })}
              >
                <RotateCcw size={16} />
              </button>
            )}
            {resize && (
              <label className="layout-width">
                <span>{t("Width")}</span>
                <select
                  aria-label={t("Width of {title}", { title })}
                  value={cardWidthPercentage(width, columns)}
                  onChange={(event) => resize(Number(event.target.value))}
                >
                  <option value={-1}>{t("Original width")}</option>
                  {widthPercentages.map((percent) => (
                    <option key={percent} value={percent}>
                      {percent === 100
                        ? t("Full row")
                        : t("{value0}%", { value0: percent })}
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
          {resizeCard &&
            [
              "left",
              "right",
              "top",
              "bottom",
              "top-left",
              "top-right",
              "bottom-left",
              "bottom-right",
            ].map((direction) => (
              <button
                key={direction}
                type="button"
                className={`layout-resize-handle resize-${direction}`}
                aria-label={t("Resize {title}: {edge}", {
                  title,
                  edge: t(direction),
                })}
                onPointerDown={(event) => {
                  if (event.button !== 0 || !element.current?.parentElement)
                    return;
                  event.preventDefault();
                  event.stopPropagation();
                  const bounds = element.current.getBoundingClientRect();
                  const parent = element.current.parentElement;
                  gesture.current = {
                    pointer: event.pointerId,
                    x: event.clientX,
                    y: event.clientY,
                    width: bounds.width,
                    height: bounds.height,
                    grid: parent.clientWidth,
                    gap: parseFloat(getComputedStyle(parent).columnGap) || 16,
                    direction,
                    size: {},
                  };
                  event.currentTarget.setPointerCapture(event.pointerId);
                  setDraft({});
                }}
                onPointerMove={(event) => {
                  const active = gesture.current;
                  if (!active || active.pointer !== event.pointerId) return;
                  const size: { width?: number; height?: number } = {};
                  if (direction.includes("left") || direction.includes("right"))
                    size.width = snapCardWidth(
                      active.width +
                        (event.clientX - active.x) *
                          (direction.includes("left") ? -1 : 1),
                      active.grid,
                      active.gap,
                    );
                  if (direction.includes("top") || direction.includes("bottom"))
                    size.height = snapCardHeight(
                      active.height +
                        (event.clientY - active.y) *
                          (direction.includes("top") ? -1 : 1),
                    );
                  active.size = size;
                  setDraft(size);
                }}
                onPointerUp={(event) => {
                  const active = gesture.current;
                  if (!active || active.pointer !== event.pointerId) return;
                  gesture.current = null;
                  resizeCard(active.size);
                  setDraft(null);
                }}
                onPointerCancel={() => {
                  gesture.current = null;
                  setDraft(null);
                }}
                onKeyDown={(event) => {
                  if (!element.current) return;
                  const delta = ["ArrowRight", "ArrowDown"].includes(event.key)
                    ? 1
                    : ["ArrowLeft", "ArrowUp"].includes(event.key)
                      ? -1
                      : 0;
                  if (!delta) return;
                  event.preventDefault();
                  event.stopPropagation();
                  const size: { width?: number; height?: number } = {};
                  if (direction.includes("left") || direction.includes("right"))
                    size.width = Math.round(
                      (Math.max(
                        3,
                        Math.min(
                          12,
                          Math.round(
                            (cardWidthPercentage(
                              width === -1
                                ? snapCardWidth(
                                    element.current.clientWidth,
                                    element.current.parentElement!.clientWidth,
                                  )
                                : width,
                              columns,
                            ) *
                              12) /
                              100,
                          ) +
                            delta * (direction.includes("left") ? -1 : 1),
                        ),
                      ) *
                        100) /
                        12,
                    );
                  if (direction.includes("top") || direction.includes("bottom"))
                    size.height = snapCardHeight(
                      element.current.clientHeight +
                        delta * 24 * (direction.includes("top") ? -1 : 1),
                    );
                  resizeCard(size);
                }}
              />
            ))}
        </>
      )}
      <div
        className="layout-item-content"
        inert={editing && !item.props["data-layout-nested"]}
      >
        {item}
      </div>
    </div>
  );
}
