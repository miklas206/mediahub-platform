import {
  useEffect,
  useRef,
  useState,
  type PointerEvent,
  type RefObject,
} from "react";
import type { GridPosition } from "./layout-grid";
import { gridPosition } from "./layout-grid";

export function useLayoutPointer(
  element: RefObject<HTMLDivElement | null>,
  place: (position: GridPosition) => void,
) {
  const [dragging, setDragging] = useState(false);
  const finish = useRef<((commit: boolean) => void) | null>(null);
  useEffect(() => () => finish.current?.(false), []);

  function start(event: PointerEvent<HTMLButtonElement>) {
    const card = element.current;
    const group = card?.parentElement;
    if (event.button !== 0 || !card || !group) return;
    finish.current?.(false);
    const bounds = card.getBoundingClientRect();
    const origin = { x: bounds.left + scrollX, y: bounds.top + scrollY };
    const anchor = {
      x: event.clientX - bounds.left,
      y: event.clientY - bounds.top,
    };
    const initial = { x: event.clientX, y: event.clientY };
    const pointer = event.pointerId;
    const surface = event.currentTarget;
    let point = initial;
    let moved = false;
    let frame = 0;
    surface.setPointerCapture(pointer);

    function draw() {
      card!.style.setProperty(
        "--layout-drag-x",
        `${point.x - anchor.x - origin.x + scrollX}px`,
      );
      card!.style.setProperty(
        "--layout-drag-y",
        `${point.y - anchor.y - origin.y + scrollY}px`,
      );
    }
    function tick() {
      if (!moved) return;
      const edge = 64;
      const speed =
        point.y < edge
          ? -Math.ceil((edge - point.y) / 4)
          : point.y > innerHeight - edge
            ? Math.ceil((point.y - innerHeight + edge) / 4)
            : 0;
      if (speed) window.scrollBy(0, Math.max(-20, Math.min(20, speed)));
      draw();
      frame = requestAnimationFrame(tick);
    }
    function move(event: globalThis.PointerEvent) {
      if (event.pointerId !== pointer) return;
      point = { x: event.clientX, y: event.clientY };
      if (!moved && Math.hypot(point.x - initial.x, point.y - initial.y) >= 5) {
        moved = true;
        setDragging(true);
        frame = requestAnimationFrame(tick);
      }
      if (moved) draw();
    }
    function wheel(event: WheelEvent) {
      if (!moved) return;
      event.preventDefault();
      window.scrollBy(
        event.deltaX,
        event.deltaY *
          (event.deltaMode === 1
            ? 24
            : event.deltaMode === 2
              ? innerHeight
              : 1),
      );
      draw();
    }
    function end(commit: boolean) {
      finish.current = null;
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("keydown", key);
      window.removeEventListener("wheel", wheel, true);
      window.removeEventListener("scroll", draw);
      if (surface.hasPointerCapture(pointer))
        surface.releasePointerCapture(pointer);
      card!.style.removeProperty("--layout-drag-x");
      card!.style.removeProperty("--layout-drag-y");
      setDragging(false);
      if (commit && moved) {
        const grid = group!.getBoundingClientRect();
        const columns = Math.max(
          3,
          Math.min(
            12,
            Math.round((bounds.width + 16) / ((grid.width + 16) / 12)),
          ),
        );
        const position = gridPosition(
          point.x - anchor.x - grid.left,
          point.y - anchor.y - grid.top,
          grid.width,
          columns,
        );
        let target =
          document
            .elementFromPoint(point.x, point.y)
            ?.closest<HTMLElement>(".layout-item") || null;
        while (target && target.parentElement !== group)
          target =
            target.parentElement?.closest<HTMLElement>(".layout-item") || null;
        if (target && target !== card)
          position.row = Math.max(
            1,
            1 +
              Math.round((target.getBoundingClientRect().top - grid.top) / 24),
          );
        place(position);
      }
    }
    function up(event: globalThis.PointerEvent) {
      if (event.pointerId === pointer) end(true);
    }
    function cancel(event: globalThis.PointerEvent) {
      if (event.pointerId === pointer) end(false);
    }
    function key(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        end(false);
      }
    }
    finish.current = end;
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("keydown", key);
    window.addEventListener("wheel", wheel, { passive: false, capture: true });
    window.addEventListener("scroll", draw);
  }
  return { dragging, start };
}
