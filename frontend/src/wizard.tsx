import { useEffect, useState, type FormEvent } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  HardDrive,
  ShieldCheck,
} from "lucide-react";
import { api, setCsrf } from "./api";
import { SecuritySettings } from "./security";
import { PlexInstallPage } from "./plex-install";
import type { User } from "./contracts";
import {
  defaultDraft,
  type Checks,
  type Review,
  type SetupDraft,
  type SetupState,
} from "./phase2-types";
import {
  CatalogPage,
  DiscoveryPanel,
  ErrorBox,
  NetworkForm,
  Panel,
  StorageEditor,
} from "./phase2";

const steps = [
  "Welcome",
  "System Check",
  "Administrator",
  "Two-factor authentication",
  "Storage",
  "Network",
  "Apps",
  "Review",
  "Apply",
  "Complete",
];
export function SetupWizard({
  user,
  hasAdmin,
  onSignedIn,
  onComplete,
}: {
  user: User | null;
  hasAdmin: boolean;
  onSignedIn: (user: User) => void;
  onComplete: () => void;
}) {
  const [draft, setDraft] = useState<SetupDraft>(defaultDraft);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [checks, setChecks] = useState<Checks>();
  const [review, setReview] = useState<Review>();
  useEffect(() => {
    if (user) {
      api<SetupState>("/setup/draft")
        .then((state) => {
          setDraft(state.draft);
          setRevision(state.revision);
        })
        .catch((e) => setError(e.message));
    }
  }, [user]);
  useEffect(() => {
    if (draft.step === 1) {
      api<Checks>(user ? "/setup/checks" : "/setup/public-checks")
        .then(setChecks)
        .catch((e) => setError(e.message));
    }
  }, [draft.step, user]);
  const save = async (next: SetupDraft) => {
    if (user) {
      const state = await api<SetupState>("/setup/draft", "PUT", {
        revision,
        draft: next,
      });
      setRevision(state.revision);
      setDraft(state.draft);
    } else setDraft(next);
  };
  const move = async (step: number) => {
    setBusy(true);
    setError("");
    try {
      await save({ ...draft, step });
      if (step === 7) setReview(await api<Review>("/setup/review"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (draft.step === 7 && user)
      api<Review>("/setup/review")
        .then(setReview)
        .catch((e) => setError(e.message));
  }, [draft.step, user]);
  const administrator = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      if (!hasAdmin && form.get("password") !== form.get("confirmation"))
        throw new Error("Passwords do not match");
      const profile = await api<User>(
        hasAdmin ? "/auth/login" : "/setup/administrator",
        "POST",
        {
          username: form.get("username"),
          password: form.get("password"),
          ...(hasAdmin ? { secondFactor: form.get("secondFactor") || "" } : {}),
          ...(!hasAdmin ? { token: form.get("token") } : {}),
        },
      );
      setCsrf(profile.csrf);
      const state = await api<SetupState>("/setup/draft");
      const saved = await api<SetupState>("/setup/draft", "PUT", {
        revision: state.revision,
        draft: {
          ...state.draft,
          step: Math.max(3, state.draft.step),
          installation_type: hasAdmin
            ? state.draft.installation_type
            : draft.installation_type,
        },
      });
      setDraft(saved.draft);
      setRevision(saved.revision);
      onSignedIn(profile);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const apply = async () => {
    setBusy(true);
    setError("");
    try {
      await api("/setup/apply", "POST", { revision });
      setDraft({ ...draft, step: 9 });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="wizard-shell">
      <aside className="wizard-sidebar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={34} />
          <span>
            Media<span>Hub</span>
          </span>
        </div>
        <p className="eyebrow">INSTALLATION</p>
        <ol>
          {steps.map((name, index) => (
            <li
              key={name}
              className={
                draft.step === index
                  ? "current"
                  : draft.step > index
                    ? "done"
                    : ""
              }
            >
              <span>
                {draft.step > index ? <Check size={14} /> : index + 1}
              </span>
              {name}
            </li>
          ))}
        </ol>
        <div className="wizard-safety">
          <ShieldCheck size={20} />
          <p>No existing services are changed. Your media stays where it is.</p>
        </div>
      </aside>
      <div className="wizard-main">
        <header>
          <span>
            SETUP · STEP {draft.step + 1} OF {steps.length}
          </span>
          <span>0.4.2</span>
        </header>
        <div className="wizard-body">
          <div className="page-heading">
            <div>
              <span className="eyebrow">YOUR SERVER, YOUR CHOICES</span>
              <h1>
                {draft.step === 0 ? "Welcome to MediaHub" : steps[draft.step]}
              </h1>
              <p>
                {draft.step === 0
                  ? "Self-hosted media management platform"
                  : "Choose how your media server should work. Existing files stay in place."}
              </p>
            </div>
          </div>
          <ErrorBox error={error} />
          {draft.step === 0 && (
            <>
              <div className="welcome-features">
                {["Media apps", "Storage", "Health", "Updates", "Backups"].map(
                  (label) => (
                    <div key={label}>
                      <HardDrive size={20} />
                      {label}
                    </div>
                  ),
                )}
              </div>
              <Panel title="A clear home for your media services">
                <p>
                  Register your existing storage, protect your account and
                  choose your apps. Plex works independently; protected
                  downloads are optional. No disk is formatted and no media is
                  moved by setup.
                </p>
                <div className="button-row">
                  <button className="primary" onClick={() => move(1)}>
                    Get Started <ArrowRight size={16} />
                  </button>
                  <button
                    onClick={() => {
                      setDraft({
                        ...draft,
                        installation_type: "import",
                        step: 1,
                      });
                    }}
                  >
                    Import Existing Setup
                  </button>
                </div>
              </Panel>
            </>
          )}
          {draft.step === 1 && (
            <Panel title="Compatibility checks">
              {checks ? (
                [...checks.core, ...checks.runtime].map((check) => (
                  <div className="check-row" key={check.name}>
                    <span
                      className={
                        "badge " +
                        (check.state === "passed"
                          ? "healthy"
                          : check.state === "failed"
                            ? "unhealthy"
                            : "degraded")
                      }
                    >
                      {check.state}
                    </span>
                    <div>
                      <strong>{check.name}</strong>
                      <p>{check.message}</p>
                    </div>
                  </div>
                ))
              ) : (
                <p>Checking the environment…</p>
              )}
              <p className="muted">
                Core can run without Docker. App installation will require a
                connected runtime.
              </p>
            </Panel>
          )}
          {draft.step === 2 && (
            <Panel
              title={
                user
                  ? "Administrator ready"
                  : hasAdmin
                    ? "Sign in to resume setup"
                    : "Create your administrator"
              }
            >
              {user ? (
                <p>
                  Signed in as {user.username}. Your existing account will be
                  kept.
                </p>
              ) : (
                <form className="admin-form" onSubmit={administrator}>
                  {!hasAdmin && (
                    <>
                      <p>
                        Read your installation token locally with{" "}
                        <code>python -m mediahub.cli bootstrap-token</code>.
                        This prevents someone else from claiming an unconfigured
                        server.
                      </p>
                      <label>
                        Installation token
                        <input
                          type="password"
                          name="token"
                          required
                          autoComplete="off"
                        />
                      </label>
                    </>
                  )}
                  <label>
                    Username
                    <input
                      name="username"
                      required
                      autoComplete="username"
                      maxLength={80}
                    />
                  </label>
                  <label>
                    Password
                    <input
                      name="password"
                      type="password"
                      required
                      minLength={hasAdmin ? 1 : 12}
                      autoComplete={
                        hasAdmin ? "current-password" : "new-password"
                      }
                    />
                  </label>
                  {!hasAdmin && (
                    <label>
                      Confirm password
                      <input
                        name="confirmation"
                        type="password"
                        required
                        autoComplete="new-password"
                      />
                    </label>
                  )}
                  {hasAdmin && (
                    <label>
                      Authenticator or recovery code
                      <input
                        name="secondFactor"
                        autoComplete="one-time-code"
                        maxLength={32}
                        placeholder="If enabled"
                      />
                    </label>
                  )}
                  <button className="primary" disabled={busy}>
                    {hasAdmin ? "Sign in & continue" : "Create administrator"}
                  </button>
                </form>
              )}
            </Panel>
          )}
          {draft.step === 3 && (
            <div className="stack">
              <SecuritySettings />
              <p className="muted">
                Protect your account with an authenticator. Save the recovery
                codes before continuing. You can also enable two-factor
                authentication later in Settings → Security.
              </p>
              <details>
                <summary>Advanced: discover an existing installation</summary>
                <div className="installation-choices">
                  {[
                    [
                      "new",
                      "New Installation",
                      "Select storage for a fresh MediaHub configuration.",
                    ],
                    [
                      "import",
                      "Import Existing Installation",
                      "Inspect existing services and save a plan — no migration.",
                    ],
                  ].map(([value, label, description]) => (
                    <button
                      className={
                        draft.installation_type === value ? "selected" : ""
                      }
                      key={value}
                      onClick={() =>
                        setDraft({
                          ...draft,
                          installation_type: value as "new" | "import",
                        })
                      }
                    >
                      <strong>{label}</strong>
                      <span>{description}</span>
                    </button>
                  ))}
                </div>
                {draft.installation_type === "import" && (
                  <DiscoveryPanel
                    selected={draft.selected_imports}
                    onSelect={(ids) =>
                      setDraft({ ...draft, selected_imports: ids })
                    }
                  />
                )}
              </details>
            </div>
          )}
          {draft.step === 4 && (
            <div className="stack">
              <Panel title="Planned storage">
                {draft.storage.length ? (
                  draft.storage.map((item, index) => (
                    <div className="storage-row" key={item.path}>
                      <HardDrive />
                      <div>
                        <strong>{item.name}</strong>
                        <code>{item.path}</code>
                        <small>
                          {item.kind} ·{" "}
                          {item.action === "create"
                            ? "Create on Apply"
                            : "Use existing, no changes"}
                        </small>
                      </div>
                      <button
                        onClick={() =>
                          setDraft({
                            ...draft,
                            storage: draft.storage.filter(
                              (_, i) => i !== index,
                            ),
                          })
                        }
                      >
                        Remove from plan
                      </button>
                    </div>
                  ))
                ) : (
                  <p className="muted">
                    No storage selected. You may finish Core setup and configure
                    media storage later.
                  </p>
                )}
              </Panel>
              <Panel title="Choose storage">
                <StorageEditor
                  onAdd={async (item) => {
                    const inspected = await api<{ path: string }>(
                      "/agent/directories/inspect",
                      "POST",
                      { path: item.path },
                    );
                    if (
                      item.action === "create" &&
                      item.confirmed_path !== inspected.path
                    )
                      throw new Error(
                        "Choose the canonical path shown by the server browser before confirming creation.",
                      );
                    await save({ ...draft, storage: [...draft.storage, item] });
                  }}
                />
              </Panel>
            </div>
          )}
          {draft.step === 5 && (
            <Panel title="Local access / bring your own proxy">
              <NetworkForm
                value={draft.network}
                onChange={(network) => setDraft({ ...draft, network })}
              />
            </Panel>
          )}
          {draft.step === 6 && (
            <div className="stack">
              <Panel title="Your first media app">
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={draft.selected_apps.includes("org.mediahub.plex")}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        selected_apps: e.target.checked
                          ? [
                              ...new Set([
                                ...draft.selected_apps,
                                "org.mediahub.plex",
                              ]),
                            ]
                          : draft.selected_apps.filter(
                              (id) => id !== "org.mediahub.plex",
                            ),
                      })
                    }
                  />
                  Install Plex now · optional
                </label>
                <p>
                  Plex works on its own. You do not need a Seedbox or VPN to
                  enjoy your own local media.
                </p>
              </Panel>
              {draft.selected_apps.includes("org.mediahub.plex") && (
                <PlexInstallPage embedded />
              )}
              <details>
                <summary>Optional apps and advanced catalog</summary>
                <CatalogPage
                  selected={draft.selected_apps}
                  onSelect={(ids) => setDraft({ ...draft, selected_apps: ids })}
                />
              </details>
            </div>
          )}
          {draft.step === 7 && (
            <div className="stack">
              <Panel title="Review your configuration">
                <dl className="review-grid">
                  <dt>Administrator</dt>
                  <dd>{user?.username}</dd>
                  <dt>Installation type</dt>
                  <dd>{draft.installation_type}</dd>
                  <dt>Storage</dt>
                  <dd>{draft.storage.length} locations</dd>
                  <dt>Network (pending)</dt>
                  <dd>
                    {draft.network.listen_host}:{draft.network.port}
                  </dd>
                  <dt>Selected apps</dt>
                  <dd>{draft.selected_apps.join(", ") || "None"}</dd>
                  <dt>Selected imports</dt>
                  <dd>{draft.selected_imports.length}</dd>
                </dl>
                {draft.storage.map((item) => (
                  <p key={item.path}>
                    <strong>
                      {item.action === "create" ? "Create" : "Reuse"}:
                    </strong>{" "}
                    <code>{item.path}</code>
                  </p>
                ))}
              </Panel>
              {review ? (
                <>
                  <Panel title="Actions on Apply">
                    {review.actions.map((action) => (
                      <p key={action}>✓ {action}</p>
                    ))}
                    <p>
                      <strong>
                        Applying Core settings does not move media or change
                        apps. Any app installed in the previous step is managed
                        separately.
                      </strong>
                    </p>
                  </Panel>
                  {review.errors.map((message) => (
                    <ErrorBox key={message} error={message} />
                  ))}
                  {review.warnings.length > 0 && (
                    <Panel title="Warnings">
                      {review.warnings.map((message) => (
                        <p className="review-warning" key={message}>
                          {message}
                        </p>
                      ))}
                    </Panel>
                  )}
                  {review.imports.map((plan) => (
                    <Panel
                      key={plan.source_id}
                      title={plan.detected_app + " — " + plan.status}
                    >
                      <p>
                        {plan.findings.join(" · ") ||
                          "Plan only — not executable"}
                      </p>
                    </Panel>
                  ))}
                </>
              ) : (
                <p>Validating review…</p>
              )}
            </div>
          )}
          {draft.step === 8 && (
            <Panel title="Apply configuration">
              <p>
                Save this Core configuration and create only the new directories
                you explicitly confirmed. Existing services and media will not
                be changed.
              </p>
              <button disabled={busy} className="primary" onClick={apply}>
                {busy ? "Applying safely…" : "Apply configuration"}
              </button>
            </Panel>
          )}
          {draft.step === 9 && (
            <Panel title="Your MediaHub is ready">
              <div className="success">
                <Check />
                Core setup complete. Your media remains in its existing folders.
              </div>
              <p>
                Agent and storage status are available in your dashboard. Open
                an available app to review its requirements and installation
                guide.
              </p>
              <button className="primary" onClick={onComplete}>
                Open dashboard <ArrowRight size={16} />
              </button>
            </Panel>
          )}
          {draft.step > 0 && draft.step < 9 && (
            <footer className="wizard-footer">
              <button disabled={busy} onClick={() => move(draft.step - 1)}>
                <ArrowLeft size={16} />
                Back
              </button>
              <span>
                {user
                  ? "Progress is saved when you continue."
                  : "Administrator authentication unlocks saved progress."}
              </span>
              {draft.step !== 8 && (draft.step !== 2 || user) && (
                <button
                  className="primary"
                  disabled={busy || (draft.step === 7 && !review?.canApply)}
                  onClick={() => move(draft.step + 1)}
                >
                  Continue <ArrowRight size={16} />
                </button>
              )}
            </footer>
          )}
        </div>
      </div>
    </main>
  );
}
