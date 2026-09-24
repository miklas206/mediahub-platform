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
