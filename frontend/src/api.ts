let csrf = "";
export const setCsrf = (value: string) => {
  csrf = value;
};

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
    const payload = await response.json();
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
  const payload = await response.json();
  if (!response.ok) {
    if (
      response.status === 401 &&
      path !== "/auth/login" &&
      payload.error?.code === "unauthorized"
    )
      window.dispatchEvent(new Event("session-expired"));
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

function uploadChunk(
  endpoint: string,
  chunk: Blob,
  onProgress: (loaded: number) => void,
  signal: AbortSignal,
): Promise<UploadSession> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    if (signal.aborted) {
      reject(new DOMException("Upload stopped", "AbortError"));
      return;
    }
    request.open("PUT", "/api/v1" + endpoint);
    request.withCredentials = true;
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.setRequestHeader("X-MediaHub-CSRF", csrf);
    const abort = () => request.abort();
    signal.addEventListener("abort", abort, { once: true });
    request.onloadend = () => signal.removeEventListener("abort", abort);
    request.upload.onprogress = (event) => onProgress(event.loaded);
    request.onerror = () =>
      reject(new Error("Upload connection was interrupted"));
    request.onabort = () =>
      reject(new DOMException("Upload stopped", "AbortError"));
    request.onload = () => {
      try {
        const payload = JSON.parse(request.responseText);
        if (request.status < 200 || request.status >= 300 || !payload.data) {
          reject(
            new Error(payload.error?.message || "Upload chunk was rejected"),
          );
        } else resolve(payload.data);
      } catch {
        reject(new Error("MediaHub returned an invalid upload response"));
      }
    };
    request.send(chunk);
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
    let offset = session.offset;
    let retries = 0;
    while (offset < file.size) {
      signal.throwIfAborted();
      const end = Math.min(offset + 8 * 1024 * 1024, file.size);
      try {
        const result = await uploadChunk(
          endpoint + "?offset=" + offset,
          file.slice(offset, end),
          (loaded) =>
            onProgress(
              Math.min(99, Math.round((100 * (offset + loaded)) / file.size)),
            ),
          signal,
        );
        if (result.offset !== end)
          throw new Error("Unexpected upload position");
        offset = result.offset;
        retries = 0;
      } catch (error) {
        signal.throwIfAborted();
        if (++retries > 2) throw error;
        // A response can be lost after the Agent has stored the chunk.
        const current = await api<UploadSession>(
          endpoint,
          "GET",
          undefined,
          signal,
        );
        if (current.offset < offset || current.offset > end) throw error;
        offset = current.offset;
      }
    }
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
