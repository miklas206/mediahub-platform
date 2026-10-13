import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ShieldAlert, X } from "lucide-react";
import { t, translateText } from "./i18n";
import "./confirmation-dialog.css";

type Options = { title?: string; confirmLabel?: string; danger?: boolean };
type Request = {
  owner: string;
  message: string;
  options: Options;
  resolve: (confirmed: boolean) => void;
  opener: HTMLElement | null;
};
type Confirmation = {
  ask: (owner: string, message: string, options?: Options) => Promise<boolean>;
  cancel: (owner: string) => void;
};
const ConfirmationContext = createContext<Confirmation>({
  ask: async () => false,
  cancel: () => {},
});

function ConfirmationDialog({
  request,
  finish,
}: {
  request: Request;
  finish: (request: Request, confirmed: boolean) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    cancelButton.current?.focus();
    return () => {
      element.close();
      if (request.opener?.isConnected) request.opener.focus();
    };
  }, [request]);
  return (
    <dialog
      ref={dialog}
      className={`confirmation-dialog${request.options.danger ? " danger" : ""}`}
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-message`}
      onCancel={(event) => {
        event.preventDefault();
        finish(request, false);
      }}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const buttons = Array.from(
          event.currentTarget.querySelectorAll<HTMLButtonElement>(
            "button:not(:disabled)",
          ),
        );
        const first = buttons[0];
        const last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
    >
      <header className="confirmation-heading">
        <span className="confirmation-icon">
          <ShieldAlert size={24} aria-hidden="true" />
        </span>
        <div>
          <span className="confirmation-brand">MediaHub</span>
          <h2 id={`${id}-title`}>
            {t(request.options.title || "Confirm action")}
          </h2>
        </div>
        <button
          type="button"
          className="confirmation-close"
          aria-label={t("Close")}
          onClick={() => finish(request, false)}
        >
          <X size={18} />
        </button>
      </header>
      <p id={`${id}-message`} className="confirmation-message">
        {translateText(request.message)}
      </p>
      <footer className="confirmation-actions">
        <button
          ref={cancelButton}
          type="button"
          autoFocus
          onClick={() => finish(request, false)}
        >
          {t("Cancel")}
        </button>
        <button
          type="button"
          className={request.options.danger ? "danger" : "primary"}
          onClick={() => finish(request, true)}
        >
          {t(request.options.confirmLabel || "Continue")}
        </button>
      </footer>
    </dialog>
  );
}

export function ConfirmationProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<Request | null>(null);
  const pending = useRef<Request | null>(null);
  const finish = useCallback((target: Request, confirmed: boolean) => {
    if (pending.current !== target) return;
    pending.current = null;
    setRequest(null);
    target.resolve(confirmed);
  }, []);
  const ask = useCallback<Confirmation["ask"]>(
    (owner, message, options = {}) => {
      // A repeated click must never queue another destructive action.
      if (pending.current) return Promise.resolve(false);
      return new Promise<boolean>((resolve) => {
        const next = {
          owner,
          message,
          options,
          resolve,
          opener:
            document.activeElement instanceof HTMLElement
              ? document.activeElement
              : null,
        };
        pending.current = next;
        setRequest(next);
      });
    },
    [],
  );
  const cancel = useCallback(
    (owner: string) => {
      if (pending.current?.owner === owner) finish(pending.current, false);
    },
    [finish],
  );
  useEffect(
    () => () => {
      pending.current?.resolve(false);
      pending.current = null;
    },
    [],
  );
  return (
    <ConfirmationContext.Provider value={{ ask, cancel }}>
      {children}
      {request && (
        <ConfirmationDialog
          key={request.owner}
          request={request}
          finish={finish}
        />
      )}
    </ConfirmationContext.Provider>
  );
}

export function useConfirm() {
  const { ask, cancel } = useContext(ConfirmationContext);
  const owner = useId();
  useEffect(() => () => cancel(owner), [cancel, owner]);
  return useCallback(
    (message: string, options?: Options) => ask(owner, message, options),
    [ask, owner],
  );
}
