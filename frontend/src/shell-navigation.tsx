import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Activity,
  Settings2,
  Menu,
  ChevronDown,
} from "lucide-react";
import { ThemeNavIcon } from "./theme-nav-icon";
import { t } from "./i18n";

export function ShellNavigation({
  placement,
  visible,
}: {
  placement: "integrated" | "dock" | "launcher";
  visible: readonly string[];
}) {
  const links = [
    ["/", "Apps", LayoutDashboard],
    ["/overview", "Overview", Activity],
    ["/settings", "Settings", Settings2],
  ] as const;
  const nav = (
    <nav
      className={`shell-navigation shell-navigation-${placement}`}
      aria-label={t("Main navigation")}
    >
      {links
        .filter(([path]) => visible.includes(path))
        .map(([path, label, Icon]) => (
          <NavLink
            to={path}
            end={path === "/"}
            key={path}
            onClick={(event) => {
              const menu = event.currentTarget.closest("details");
              if (menu) menu.open = false;
            }}
          >
            <ThemeNavIcon path={path} fallback={Icon} />
            <span>{t(label)}</span>
          </NavLink>
        ))}
    </nav>
  );
  return placement === "launcher" ? (
    <details className="shell-launcher">
      <summary>
        <Menu size={17} />
        {t("Navigation")}
        <ChevronDown size={13} />
      </summary>
      {nav}
    </details>
  ) : (
    nav
  );
}
