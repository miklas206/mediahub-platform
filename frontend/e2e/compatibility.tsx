// Browser-only entry for retained components which have no public route.
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
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
const views = {
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
  createRoot(document.getElementById("root")!).render(
    <BrowserRouter>
      <NotificationProvider>
        <ConfirmationProvider>{views[view]}</ConfirmationProvider>
      </NotificationProvider>
    </BrowserRouter>,
  );
});
