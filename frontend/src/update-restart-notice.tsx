import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";

export function UpdateRestartNotice({
  disconnected,
}: {
  disconnected: boolean;
}) {
  const [takingLonger, setTakingLonger] = useState(false);
  useEffect(() => {
    setTakingLonger(false);
    if (!disconnected) return;
    const timer = window.setTimeout(() => setTakingLonger(true), 180_000);
    return () => window.clearTimeout(timer);
  }, [disconnected]);

  return (
    <div className="update-restart-notice" role="status" aria-live="polite">
      <LoaderCircle className="spin" size={20} aria-hidden="true" />
      <div>
        <strong>
          {takingLonger
            ? "MediaHub is taking longer to reconnect"
            : disconnected
              ? "Please wait while MediaHub comes back online"
              : "Update in progress ? a short restart is expected"}
        </strong>
        <p>
          {takingLonger
            ? "We are still trying automatically. Completion has not been confirmed. If the connection does not return, check the update console or server status."
            : disconnected
              ? "The connection can briefly disappear while MediaHub restarts after an update. This alone does not mean the update failed. Give it a little time; we will reconnect and check the result automatically."
              : "MediaHub may briefly go offline during installation. This is expected. The update continues on the server, even if you close this page."}
        </p>
        <p className="muted">
          You do not need to refresh or start the update again.
        </p>
      </div>
    </div>
  );
}
