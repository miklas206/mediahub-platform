import { useEffect, useState } from "react";
import { api } from "./api";
import { ErrorBox } from "./phase2";
type Status = {
  status: string;
  message: string;
  checkedAt: number | null;
  address?: string;
  port?: number;
};
export function PortReachability({
  address,
  port,
  eligible,
}: {
  address?: string | null;
  port?: number | null;
  eligible: boolean;
}) {
  const [value, setValue] = useState<Status>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const data = await api<Status>("/seedbox/port-reachability");
        if (active) {
          setValue(data);
          setError("");
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    };
    void load();
    const timer = setInterval(() => void load(), 10000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  const current =
    eligible &&
    value?.address === address &&
    value?.port === port &&
    !!value?.checkedAt &&
    Date.now() / 1000 - value.checkedAt < 90;
  const state = current ? value.status : "unknown";
  return (
    <div className="port-reachability">
      <div className="runtime-row">
        <strong>Incoming TCP connection</strong>
        <span
          className={
            state === "reachable"
              ? "success"
              : state === "unreachable"
                ? "danger"
                : "muted"
          }
        >
          {state === "reachable"
            ? "Reachable from Core"
            : state === "unreachable"
              ? "Not reachable from Core"
              : "Not verified"}
        </span>
      </div>
      <p className="muted">
        {current
          ? value.message
          : "Waiting for a check of the current VPN address and port."}
      </p>
      <p className="muted">
        Checked every minute from MediaHub Core, outside the torrent VPN
        namespace. A successful TCP test does not verify UDP or guarantee every
        peer can connect.
        {value?.checkedAt
          ? ` Last check: ${new Date(value.checkedAt * 1000).toLocaleTimeString()}.`
          : ""}
      </p>
      <ErrorBox error={error} />
      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            setValue(await api<Status>("/seedbox/port-reachability", "POST"));
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Checking port?" : "Check incoming connection"}
      </button>
    </div>
  );
}
