import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Application } from "./ui";
import { NotificationProvider } from "./notification-popup";
import { ConfirmationProvider } from "./confirmation-dialog";
import "./styles.css";
import "./phase2.css";
import "./security.css";
import "./checkboxes.css";
import "./workspace-redesign.css";
import "./reference-workspace.css";
import "./sidebar-themes.css";
import "./navigation-layouts.css";
import "./select-controls.css";
import "./brand-icons.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <NotificationProvider><ConfirmationProvider><Application /></ConfirmationProvider></NotificationProvider>
    </BrowserRouter>
  </StrictMode>,
);
