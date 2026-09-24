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
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    method,
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

export function uploadMediaFile<T>(
  locationId: string,
  path: string,
  file: File,
  onProgress: (percent: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const query = new URLSearchParams({ path, filename: file.name });
    const request = new XMLHttpRequest();
    request.open(
      "POST",
      `/api/v1/storage/locations/${encodeURIComponent(locationId)}/files/upload?${query}`,
    );
    request.withCredentials = true;
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.setRequestHeader("X-MediaHub-CSRF", csrf);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };
    request.onerror = () => reject(new Error("Upload connection was interrupted"));
    request.onabort = () => reject(new Error("Upload was cancelled"));
    request.onload = () => {
      let payload: {
        data?: T;
        error?: { code?: string; message?: string } | null;
      } = {};
      try {
        payload = JSON.parse(request.responseText);
      } catch {
        reject(new Error("MediaHub returned an invalid upload response"));
        return;
      }
      if (request.status === 401 && payload.error?.code === "unauthorized") {
        window.dispatchEvent(new Event("session-expired"));
      }
      if (request.status < 200 || request.status >= 300 || payload.data === undefined) {
        reject(new Error(payload.error?.message || "File could not be uploaded"));
        return;
      }
      onProgress(100);
      resolve(payload.data);
    };
    request.send(file);
  });
}
