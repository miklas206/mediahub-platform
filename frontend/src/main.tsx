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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <NotificationProvider><ConfirmationProvider><Application /></ConfirmationProvider></NotificationProvider>
    </BrowserRouter>
  </StrictMode>,
);
