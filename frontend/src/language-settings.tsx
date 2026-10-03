import { useState } from "react";
import { api } from "./api";
import { Panel, ErrorBox } from "./phase2";
import { setLanguage, t, useLanguage, type Language } from "./i18n";

export function LanguageSettings() {
  const language = useLanguage();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(value: Language) {
    setBusy(true);
    setError("");
    try {
      const preferences = await api<{ language: Language }>(
        "/auth/preferences",
        "PUT",
        { language: value },
      );
      setLanguage(preferences.language);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Panel title={t("Language")}>
      <ErrorBox error={error} />
      <label>
        {t("Language")}
        <select
          aria-label={t("Language")}
          value={language}
          disabled={busy}
          onChange={(event) => void save(event.target.value as Language)}
        >
          <option value="da">Dansk</option>
          <option value="en">English</option>
        </select>
      </label>
      <p className="muted">{t("Saved for your account on all devices.")}</p>
    </Panel>
  );
}
