import {
  Children,
  createContext,
  isValidElement,
  useContext,
  useRef,
  useState,
  type ReactNode,
  type ReactElement,
} from "react";
import {
  ArrowDown,
  ArrowUp,
  GripVertical,
  LayoutGrid,
  RotateCcw,
} from "lucide-react";
import "./page-layout.css";

type Layouts = Record<string, string[]>;
type LayoutContext = {
  editing: boolean;
  layouts: Layouts;
  save: (group: string, order: string[]) => void;
};
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
  const [message, setMessage] = useState("");
  function persist(next: Layouts) {
    setLayouts(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
      setMessage("Layout saved in this browser.");
    } catch {
      setMessage(
        "Layout changed, but this browser could not save it. It will reset when you reload.",
      );
    }
  }
  return (
    <Context.Provider
      value={{
        editing,
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
          {editing ? "Done arranging" : "Customize layout"}
        </button>
        {editing && (
          <>
            <span>
              Drag a box by its handle, or use the arrows. Saved per page in
              this browser.
            </span>
            <button type="button" onClick={() => persist({})}>
              <RotateCcw size={15} /> Reset this page
            </button>
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

function canMove(
  node: ReactNode,
): node is ReactElement<Record<string, unknown>> {
  if (!isValidElement<Record<string, unknown>>(node)) return false;
  if (
    "error" in node.props ||
    node.props.role === "alert" ||
    node.props.role === "status"
  )
    return false;
  if (typeof node.type !== "string") return true;
  return (
    ["div", "section", "article", "details", "form"].includes(node.type) &&
    !/notice|success|skeleton|tabs|toolbar|button-row/.test(
      String(node.props.className || ""),
    )
  );
}

export function LayoutGroup({
  id,
  className = "stack",
  children,
}: {
  id: string;
  className?: string;
  children: ReactNode;
}) {
  const context = useContext(Context);
  const nodes = Children.toArray(children);
  const movable = nodes.filter(canMove);
  const byId = new Map(movable.map((node) => [String(node.key), node]));
  const ids = orderedIds([...byId.keys()], context?.layouts[id]);
  const [announcement, setAnnouncement] = useState("");
  function move(source: string, target: string) {
    if (
      !context ||
      source === target ||
      !ids.includes(source) ||
      !ids.includes(target)
    )
      return;
    const next = ids.filter((item) => item !== source);
    next.splice(ids.indexOf(target), 0, source);
    // Keep unavailable cards in the preference so a temporary loading state does not erase them.
    context.save(id, [
      ...next,
      ...(context.layouts[id] || []).filter((item) => !ids.includes(item)),
    ]);
    setAnnouncement(
      `Box moved to position ${next.indexOf(source) + 1} of ${ids.length}.`,
    );
  }
  let cursor = 0;
  return (
    <div className={`${className} layout-group`}>
      {nodes.map((node) => {
        if (!canMove(node)) return node;
        const itemId = ids[cursor++];
        const item = byId.get(itemId)!;
        const index = ids.indexOf(itemId);
        return (
          <LayoutItem
            key={itemId}
            item={item}
            editing={!!context?.editing && ids.length > 1}
            group={id}
            itemId={itemId}
            index={index}
            count={ids.length}
            moveBy={(delta) => move(itemId, ids[index + delta])}
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
}: {
  item: ReactElement<Record<string, unknown>>;
  editing: boolean;
  group: string;
  itemId: string;
  index: number;
  count: number;
  moveBy: (delta: number) => void;
  onDrop: (source: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [over, setOver] = useState(false);
  const title =
    typeof item.props.title === "string"
      ? item.props.title
      : ref.current?.querySelector("h2, h3, summary strong, strong")
          ?.textContent || `Box ${index + 1}`;
  return (
    <div
      ref={ref}
      className={`layout-item ${editing ? "is-arranging" : ""} ${over ? "is-drop-target" : ""}`}
      data-layout-item={itemId}
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
        <div className="layout-item-tools">
          <button
            type="button"
            className="layout-drag-handle"
            draggable
            aria-label={`Move ${title}`}
            title="Drag to move, or use the arrow keys"
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
            <GripVertical size={17} />
            <span>{title}</span>
          </button>
          <button
            type="button"
            aria-label={`Move ${title} earlier`}
            disabled={index === 0}
            onClick={() => moveBy(-1)}
          >
            <ArrowUp size={16} />
          </button>
          <button
            type="button"
            aria-label={`Move ${title} later`}
            disabled={index === count - 1}
            onClick={() => moveBy(1)}
          >
            <ArrowDown size={16} />
          </button>
        </div>
      )}
      {item}
    </div>
  );
}
