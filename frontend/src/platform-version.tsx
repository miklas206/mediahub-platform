import { useEffect, useState } from "react";

// Read release metadata at runtime so a backend release can reuse the UI bundle.
export function PlatformVersion() {
  const [version, setVersion] = useState("…");
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/health", { signal: controller.signal, cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("Health unavailable");
        return response.json();
      })
      .then(({ data }) => {
        if (typeof data?.version === "string") setVersion(data.version);
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);
  return <>{version}</>;
}
