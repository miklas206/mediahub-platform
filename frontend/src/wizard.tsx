import { translateText, t, setLanguage } from "./i18n";

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
import { PlatformVersion } from "./platform-version";
import { adjacentSetupStep, normalizeSetupStep } from "./wizard-flow";
import type { User } from "./contracts";
import {
  defaultDraft,
  type Checks,
  type Review,
  type SetupDraft,
  type SetupState,
} from "./phase2-types";
import {
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
const visibleSteps = steps.map((name, step) => ({ name, step })).filter(({ step }) => step !== 6);

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
  const [totpEnabled, setTotpEnabled] = useState<boolean>();
  const [checks, setChecks] = useState<Checks>();
  const [review, setReview] = useState<Review>();
  useEffect(() => {
    if (user) {
      api<SetupState>("/setup/draft")
        .then((state) => {
          setDraft({ ...state.draft, step: normalizeSetupStep(state.draft.step), selected_apps: [] });
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
        draft: { ...next, selected_apps: [] },
      });
      setRevision(state.revision);
      setDraft({ ...state.draft, step: normalizeSetupStep(state.draft.step), selected_apps: [] });
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
          ...(!hasAdmin ? { language: form.get("language") || "en" } : {}),
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
            {t("Media")}
            <span>{t("Hub")}</span>
          </span>
        </div>
        <p className="eyebrow">{t("INSTALLATION")}</p>
        <ol>
          {visibleSteps.map(({ name, step }, index) => (
            <li
              key={name}
              className={
                draft.step === step
                  ? "current"
                  : draft.step > step
                    ? "done"
                    : ""
              }
            >
              <span>
                {draft.step > step ? <Check size={14} /> : index + 1}
              </span>
              {t(name)}
            </li>
          ))}
        </ol>
        <div className="wizard-safety">
          <ShieldCheck size={20} />
          <p>
            {t(
              "No existing services are changed. Your media stays where it is.",
            )}
          </p>
        </div>
      </aside>
      <div className="wizard-main">
        <header>
          <span>
            {t("SETUP · STEP ")}
            {visibleSteps.findIndex(({ step }) => step === draft.step) + 1}
            {t(" OF ")}
            {visibleSteps.length}
          </span>
          <span>
            <PlatformVersion />
          </span>
        </header>
        <div className="wizard-body">
          <div className="page-heading">
            <div>
              <span className="eyebrow">{t("YOUR SERVER, YOUR CHOICES")}</span>
              <h1>
                {draft.step === 0
                  ? t("Welcome to MediaHub")
                  : translateText(steps[draft.step])}
              </h1>
              <p>
                {draft.step === 0
                  ? t("Self-hosted media management platform")
                  : t(
                      "Choose how your media server should work. Existing files stay in place.",
                    )}
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
                      {translateText(label)}
                    </div>
                  ),
                )}
              </div>
              <Panel title={t("A clear home for your media services")}>
                <p>
                  {t(
                    "Register your existing storage, protect your account and choose your apps. Plex works independently; protected downloads are optional. No disk is formatted and no media is moved by setup.",
                  )}
                </p>
                <div className="button-row">
                  <button className="primary" onClick={() => move(1)}>
                    {t("Get Started ")}
                    <ArrowRight size={16} />
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
                    {t("Import Existing Setup")}
                  </button>
                </div>
              </Panel>
            </>
          )}
          {draft.step === 1 && (
            <Panel title={t("Compatibility checks")}>
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
                      {translateText(check.state)}
                    </span>
                    <div>
                      <strong>{check.name}</strong>
                      <p>{translateText(check.message)}</p>
                    </div>
                  </div>
                ))
              ) : (
                <p>{t("Checking the environment…")}</p>
              )}
              <p className="muted">
                {t(
                  "Core can run without Docker. App installation will require a connected runtime.",
                )}
              </p>
            </Panel>
          )}
          {draft.step === 2 && (
            <Panel
              title={
                user
                  ? t("Administrator ready")
                  : hasAdmin
                    ? t("Sign in to resume setup")
                    : t("Create your administrator")
              }
            >
              {user ? (
                <p>
                  {t("Signed in as ")}
                  {user.username}
                  {t(". Your existing account will be kept.")}
                </p>
              ) : (
                <form className="admin-form" onSubmit={administrator}>
                  {!hasAdmin && <label>{t("Language")}<select name="language" defaultValue="en" onChange={event => setLanguage(event.target.value === "da" ? "da" : "en")}><option value="da">{t("Dansk")}</option><option value="en">{t("English")}</option></select></label>}
                  <label>
                    {t("Username")}
                    <input
                      name="username"
                      required
                      autoComplete="username"
                      maxLength={80}
                    />
                  </label>
                  <label>
                    {t("Password")}
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
                      {t("Confirm password")}
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
                      {t("Authenticator or recovery code")}
                      <input
                        name="secondFactor"
                        autoComplete="one-time-code"
                        maxLength={32}
                        placeholder={t("If enabled")}
                      />
                    </label>
                  )}
                  <button className="primary" disabled={busy}>
                    {hasAdmin
                      ? t("Sign in & continue")
                      : t("Create administrator")}
                  </button>
                </form>
              )}
            </Panel>
          )}
          {draft.step === 3 && (
            <div className="stack">
              <SecuritySettings setup onProtectionChange={setTotpEnabled} />
              <p className="muted">
                {t(
                  "Protect your account with an authenticator. Save the recovery codes before continuing. You can also enable two-factor authentication later in Settings → Security.",
                )}
              </p>
              <details>
                <summary>
                  {t("Advanced: discover an existing installation")}
                </summary>
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
                      <strong>{translateText(label)}</strong>
                      <span>{translateText(description)}</span>
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
              <Panel title={t("Planned storage")}>
                {draft.storage.length ? (
                  draft.storage.map((item, index) => (
                    <div className="storage-row" key={item.path}>
                      <HardDrive />
                      <div>
                        <strong>{item.name}</strong>
                        <code>{item.path}</code>
                        <small>
                          {translateText(item.kind)} ·{" "}
                          {item.action === "create"
                            ? t("Create on Apply")
                            : t("Use existing, no changes")}
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
                        {t("Remove from plan")}
                      </button>
                    </div>
                  ))
                ) : (
                  <p className="muted">
                    {t(
                      "No storage selected. You may finish Core setup and configure media storage later.",
                    )}
                  </p>
                )}
              </Panel>
              <Panel title={t("Choose storage")}>
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
            <Panel title={t("Local access / bring your own proxy")}>
              <NetworkForm
                value={draft.network}
                onChange={(network) => setDraft({ ...draft, network })}
              />
            </Panel>
          )}
          {draft.step === 7 && (
            <div className="stack">
              <Panel title={t("Review your configuration")}>
                <dl className="review-grid">
                  <dt>{t("Administrator")}</dt>
                  <dd>{user?.username}</dd>
                  <dt>{t("Installation type")}</dt>
                  <dd>{draft.installation_type}</dd>
                  <dt>{t("Storage")}</dt>
                  <dd>
                    {draft.storage.length}
                    {t(" locations")}
                  </dd>
                  <dt>{t("Network (pending)")}</dt>
                  <dd>
                    {draft.network.listen_host}:{draft.network.port}
                  </dd>
                  <dt>{t("Selected imports")}</dt>
                  <dd>{draft.selected_imports.length}</dd>
                </dl>
                {draft.storage.map((item) => (
                  <p key={item.path}>
                    <strong>
                      {item.action === "create" ? t("Create") : t("Reuse")}:
                    </strong>{" "}
                    <code>{item.path}</code>
                  </p>
                ))}
              </Panel>
              {review ? (
                <>
                  <Panel title={t("Actions on Apply")}>
                    {review.actions.map((action) => (
                      <p key={action}>✓ {action}</p>
                    ))}
                    <p>
                      <strong>
                        {t(
                          "Finish MediaHub setup first. Install your apps from the hub afterwards. Your existing media stays in place.",
                        )}
                      </strong>
                    </p>
                  </Panel>
                  {review.errors.map((message) => (
                    <ErrorBox key={message} error={message} />
                  ))}
                  {review.warnings.length > 0 && (
                    <Panel title={t("Warnings")}>
                      {review.warnings.map((message) => (
                        <p className="review-warning" key={message}>
                          {translateText(message)}
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
                          t("Plan only — not executable")}
                      </p>
                    </Panel>
                  ))}
                </>
              ) : (
                <p>{t("Validating review…")}</p>
              )}
            </div>
          )}
          {draft.step === 8 && (
            <Panel title={t("Apply configuration")}>
              <p>
                {t(
                  "Save this Core configuration and create only the new directories you explicitly confirmed. Existing services and media will not be changed.",
                )}
              </p>
              <button disabled={busy} className="primary" onClick={apply}>
                {busy ? t("Applying safely…") : t("Apply configuration")}
              </button>
            </Panel>
          )}
          {draft.step === 9 && (
            <Panel title={t("Your MediaHub is ready")}>
              <div className="success">
                <Check />
                {t(
                  "Core setup complete. Your media remains in its existing folders.",
                )}
              </div>
              <p>
                {t(
                  "Agent and storage status are available in your dashboard. Open an available app to review its requirements and installation guide.",
                )}
              </p>
              <button className="primary" onClick={onComplete}>
                {t("Open dashboard ")}
                <ArrowRight size={16} />
              </button>
            </Panel>
          )}
          {draft.step > 0 && draft.step < 9 && (
            <footer className="wizard-footer">
              <button disabled={busy} onClick={() => move(adjacentSetupStep(draft.step, -1))}>
                <ArrowLeft size={16} />
                {t("Back")}
              </button>
              <span>
                {user
                  ? t("Progress is saved when you continue.")
                  : t("Administrator authentication unlocks saved progress.")}
              </span>
              {draft.step !== 8 && (draft.step !== 2 || user) && (
                <button
                  className="primary"
                  disabled={busy || (draft.step === 3 && totpEnabled === undefined) || (draft.step === 7 && !review?.canApply)}
                  onClick={() => move(adjacentSetupStep(draft.step, 1))}
                >
                  {t(draft.step === 3 && !totpEnabled ? "Continue without 2FA" : "Continue ")}
                  <ArrowRight size={16} />
                </button>
              )}
            </footer>
          )}
        </div>
      </div>
    </main>
  );
}
