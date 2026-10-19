import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export function loadData<T>(
  path: string,
  onData: (data: T) => void,
  onError: (message: string) => void,
) {
  const controller = new AbortController();
  let retry: ReturnType<typeof setTimeout> | undefined;
  const attempt = async (number: number) => {
    try {
      const value = await api<T>(path, "GET", undefined, controller.signal);
      if (!controller.signal.aborted) onData(value);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (number < 2) {
        retry = setTimeout(() => void attempt(number + 1), 900 * (number + 1));
      } else {
        onError(error instanceof Error ? error.message : String(error));
      }
    }
  };
  void attempt(0);
  return () => {
    controller.abort();
    clearTimeout(retry);
  };
}

export function useData<T>(path: string) {
  const [result, setResult] = useState<{
    path: string;
    data?: T;
    error: string;
  }>({ path, error: "" });
  const request = useRef<(() => void) | undefined>(undefined);
  const pending = useRef(false);
  const activePath = useRef(path);
  const start = useCallback(
    (force: boolean) => {
      // Polling must neither cancel a slow read nor clear an unresolved error.
      // Clearing it would remount the same notification on every failed poll.
      if (!force && pending.current && activePath.current === path) return;
      request.current?.();
      pending.current = true;
      activePath.current = path;
      request.current = loadData<T>(
        path,
        (value) => {
          pending.current = false;
          setResult({ path, data: value, error: "" });
        },
        (error) => {
          pending.current = false;
          setResult((current) => ({
            path,
            data: current.path === path ? current.data : undefined,
            error,
          }));
        },
      );
    },
    [path],
  );
  const reload = useCallback(() => start(true), [start]);
  const poll = useCallback(() => start(false), [start]);
  useEffect(() => {
    reload();
    return () => {
      request.current?.();
      pending.current = false;
    };
  }, [reload]);
  return {
    data: result.path === path ? result.data : undefined,
    error: result.path === path ? result.error : "",
    reload,
    poll,
  };
}
