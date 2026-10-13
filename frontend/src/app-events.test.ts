import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { batchAppHealthRefresh, trackLiveConnection } from "./app-events";

it("distinguishes initial connection from failures and reconnects", () => {
  const source = new EventTarget();
  const changed = vi.fn();
  const dispose = trackLiveConnection(source, changed);
  expect(changed.mock.calls).toEqual([["connecting"]]);
  source.dispatchEvent(new Event("open"));
  expect(changed).toHaveBeenLastCalledWith("connected");
  source.dispatchEvent(new Event("error"));
  expect(changed).toHaveBeenLastCalledWith("disconnected");
  source.dispatchEvent(new Event("open"));
  expect(changed).toHaveBeenLastCalledWith("connected");
  dispose();
  changed.mockClear();
  source.dispatchEvent(new Event("error"));
  expect(changed).not.toHaveBeenCalled();
});

it("still reports a real failure before the first connection opens", () => {
  const source = new EventTarget();
  const changed = vi.fn();
  const dispose = trackLiveConnection(source, changed);
  source.dispatchEvent(new Event("error"));
  expect(changed.mock.calls).toEqual([["connecting"], ["disconnected"]]);
  dispose();
});

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

it("coalesces per-app initial and live health events into one registry refresh", () => {
  const refresh = vi.fn();
  const batch = batchAppHealthRefresh(refresh);
  for (let i = 0; i < 8; i++) batch.changed();
  expect(refresh).not.toHaveBeenCalled();
  vi.advanceTimersByTime(100);
  expect(refresh).toHaveBeenCalledTimes(1);
  batch.changed();
  vi.advanceTimersByTime(100);
  expect(refresh).toHaveBeenCalledTimes(2);
  batch.dispose();
});

it("bounds refresh delay even when more health events arrive", () => {
  const refresh = vi.fn();
  const batch = batchAppHealthRefresh(refresh);
  batch.changed();
  vi.advanceTimersByTime(90);
  batch.changed();
  vi.advanceTimersByTime(10);
  expect(refresh).toHaveBeenCalledTimes(1);
  batch.dispose();
});

it("cancels a scheduled registry refresh when the stream closes", () => {
  const refresh = vi.fn();
  const batch = batchAppHealthRefresh(refresh);
  batch.changed();
  batch.dispose();
  vi.runAllTimers();
  expect(refresh).not.toHaveBeenCalled();
});
