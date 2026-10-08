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
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const request = useRef<(() => void) | undefined>(undefined);
  const reload = useCallback(() => {
    request.current?.();
    setError("");
    request.current = loadData<T>(
      path,
      (value) => {
        setData(value);
        setError("");
      },
      setError,
    );
  }, [path]);
  useEffect(() => {
    reload();
    return () => request.current?.();
  }, [reload]);
  return { data, error, reload };
}
