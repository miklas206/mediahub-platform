export type LiveConnectionState = "connecting" | "connected" | "disconnected";

export function trackLiveConnection(
  source: {
    addEventListener(type: "open" | "error", listener: () => void): void;
    removeEventListener(type: "open" | "error", listener: () => void): void;
  },
  changed: (state: LiveConnectionState) => void,
) {
  changed("connecting");
  const opened = () => changed("connected");
  const failed = () => changed("disconnected");
  source.addEventListener("open", opened);
  source.addEventListener("error", failed);
  return () => {
    source.removeEventListener("open", opened);
    source.removeEventListener("error", failed);
  };
}

export function batchAppHealthRefresh(refresh: () => void) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return {
    changed() {
      if (timer !== undefined) return;
      // The stream reports each app separately, including its initial snapshot.
      timer = setTimeout(() => {
        timer = undefined;
        refresh();
      }, 100);
    },
    dispose() {
      clearTimeout(timer);
      timer = undefined;
    },
  };
}
