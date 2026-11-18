import {
  IntegrationAppLinks,
  IntegrationAppCard,
  FjordHubHome,
  type Integration,
} from "../src/integrations";
import { FjordFlixDashboardCard } from "../src/fjordflix-dashboard";
// Browser-only entry for retained components which have no public route.
import { createRoot } from "react-dom/client";
import { BrowserRouter, MemoryRouter, Routes, Route } from "react-router-dom";
import { api, setCsrf } from "../src/api";
import { Apps, SettingsPage } from "../src/ui";
import { useData } from "../src/use-data";
import type { AppInfo } from "../src/contracts";
import { LogicalStoragePanel } from "../src/hosts";
import {
  CatalogPage,
  MediaFiles,
  RuntimePanel,
  StorageSummary,
} from "../src/phase2";
import { NotificationProvider } from "../src/notification-popup";
import { CloudflareSetupManager } from "../src/cloudflare-setup";
import { ConfirmationProvider } from "../src/confirmation-dialog";

function MockApps() {
  const { data, error, reload } = useData<AppInfo[]>("/apps");
  return <Apps data={data} error={error} reload={reload} integrations={[]} />;
}
function IntegrationCards() {
  const { data } = useData<Integration[]>("/integrations");
  if (!data) return null;
  return (
    <>
      <IntegrationAppLinks items={data} />
      {data.map((row) => (
        <section key={row.id}>
          <IntegrationAppCard row={row} title={row.name} />
          <FjordFlixDashboardCard row={row} />
        </section>
      ))}
    </>
  );
}
const views = {
  integrations: <IntegrationCards />,
  readOnlyIntegration: (
    <Routes>
      <Route
        path="/integrations/:integrationId"
        element={<FjordHubHome administrator={false} username="viewer" />}
      />
    </Routes>
  ),
  cloudflare: <CloudflareSetupManager onSaved={() => {}} />,
  catalog: <CatalogPage />,
  files: <MediaFiles />,
  mapping: <LogicalStoragePanel />,
  apps: <MockApps />,
  preferences: <SettingsPage />,
  runtime: (
    <>
      <RuntimePanel />
      <StorageSummary />
    </>
  ),
};
const view = new URLSearchParams(location.search).get(
  "view",
) as keyof typeof views;
api<{ csrf: string }>("/auth/me").then((me) => {
  setCsrf(me.csrf);
  const content = (
    <NotificationProvider>
      <ConfirmationProvider>{views[view]}</ConfirmationProvider>
    </NotificationProvider>
  );
  createRoot(document.getElementById("root")!).render(
    view === "integrations" || view === "readOnlyIntegration" ? (
      <MemoryRouter initialEntries={["/integrations/hub"]}>
        {content}
      </MemoryRouter>
    ) : (
      <BrowserRouter>{content}</BrowserRouter>
    ),
  );
});
