import { serviceSnapshots } from "./service-snapshots";

let csrf = "";
export const setCsrf = (value: string) => {
  serviceSnapshots.clear();
  csrf = value;
};

export class ApiResponseError extends Error {
  constructor(public readonly status: number) {
    super(
      "MediaHub returned an unexpected response. The server or proxy may be restarting. Try again shortly.",
    );
    this.name = "ApiResponseError";
  }
}

async function readApiPayload(response: Response) {
  let payload;
  try {
    payload = await response.json();
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    // Proxies may return an HTML error page while Core is restarting.
    // Never display that body or retry an installation POST here.
    throw new ApiResponseError(response.status);
  }
  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload) ||
    (response.ok && !Object.prototype.hasOwnProperty.call(payload, "data"))
  ) {
    throw new ApiResponseError(response.status);
  }
  return payload;
}

export async function downloadBackup(
  data: unknown,
  scope = "core",
): Promise<Blob> {
  const endpoint =
    scope === "core"
      ? "/backups/export"
      : `/backups/apps/${encodeURIComponent(scope)}/export`;
  const response = await fetch("/api/v1" + endpoint, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-MediaHub-CSRF": csrf },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const payload = await readApiPayload(response);
    throw new Error(payload.error?.message || "Backup could not be created");
  }
  return response.blob();
}

export async function api<T>(
  path: string,
  method = "GET",
  data?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    method,
    signal,
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(method !== "GET" ? { "X-MediaHub-CSRF": csrf } : {}),
    },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  const payload = await readApiPayload(response);
  signal?.throwIfAborted();
  if (!response.ok) {
    if (
      response.status === 401 &&
      path !== "/auth/login" &&
      payload.error?.code === "unauthorized"
    ) {
      serviceSnapshots.clear();
      window.dispatchEvent(new Event("session-expired"));
    }
    throw new Error(
      payload.error?.message || "MediaHub is temporarily unavailable",
    );
  }
  return payload.data;
}

type UploadSession = {
  id: string;
  offset: number;
  size: number;
  complete: boolean;
};

async function uploadWithTus(
  endpoint: string,
  file: File,
  onProgress: (percent: number) => void,
  signal: AbortSignal,
): Promise<void> {
  signal.throwIfAborted();
  const { Upload } = await import("tus-js-client");
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const cleanup = () => signal.removeEventListener("abort", abort);
    const upload = new Upload(file, {
      uploadUrl: new URL("/api/v1" + endpoint, window.location.origin).href,
      chunkSize: 5 * 1024 * 1024,
      retryDelays: [0, 1000, 3000],
      storeFingerprintForResuming: false,
      headers: { "X-MediaHub-CSRF": csrf },
      onProgress: (sent, total) => {
        if (!signal.aborted)
          onProgress(
            total ? Math.min(99, Math.round((100 * sent) / total)) : 0,
          );
      },
      onSuccess: () => {
        cleanup();
        resolve();
      },
      onError: (error) => {
        cleanup();
        reject(error);
      },
    });
    const abort = () => {
      cleanup();
      // Stop the active tus request/retry before the existing session cleanup runs.
      void upload
        .abort()
        .then(
          () => reject(new DOMException("Upload stopped", "AbortError")),
          reject,
        );
    };
    signal.addEventListener("abort", abort, { once: true });
    upload.start();
  });
}

export async function uploadMediaFile(
  locationId: string,
  path: string,
  file: File,
  onProgress: (percent: number) => void,
  signal: AbortSignal = new AbortController().signal,
): Promise<UploadSession> {
  const base = `/storage/locations/${encodeURIComponent(locationId)}/uploads`;
  const session = await api<UploadSession>(
    base,
    "POST",
    {
      path,
      filename: file.name,
      size: file.size,
    },
    signal,
  );
  const endpoint = base + "/" + session.id;
  try {
    await uploadWithTus(endpoint, file, onProgress, signal);
    signal.throwIfAborted();
    let result: UploadSession;
    try {
      result = await api<UploadSession>(
        endpoint + "/finish",
        "POST",
        {},
        signal,
      );
    } catch (error) {
      signal.throwIfAborted();
      result = await api<UploadSession>(endpoint, "GET", undefined, signal);
      if (!result.complete) throw error;
    }
    if (!result.complete) throw new Error("Upload was not finalized");
    onProgress(100);
    return result;
  } finally {
    // Remove session metadata or unfinished data; completed media is never deleted.
    // A disconnected browser is covered by the Agent's stale-session cleanup.
    await api(endpoint, "DELETE", undefined, AbortSignal.timeout(15000)).catch(
      () => {},
    );
  }
}
