import {
  House,
  CircleGauge,
  SlidersHorizontal,
  PanelsTopLeft,
  ChartNoAxesCombined,
  SquareTerminal,
  Layers3,
  ChartArea,
  Settings,
  LayoutGrid,
  Gauge,
  SlidersVertical,
  type LucideIcon,
} from "lucide-react";

const variants: Record<string, [LucideIcon, LucideIcon, LucideIcon]> = {
  "soft-orbit": [House, CircleGauge, SlidersHorizontal],
  "precision-terminal": [PanelsTopLeft, ChartNoAxesCombined, SquareTerminal],
  "floating-layers": [Layers3, ChartArea, Settings],
  "edge-signal": [LayoutGrid, Gauge, SlidersVertical],
};
/** CSS selects the icon using the same live-preview theme as the page. */
export function ThemeNavIcon({
  path,
  fallback: Default,
}: {
  path: string;
  fallback: LucideIcon;
}) {
  const index = ["/", "/overview", "/settings"].indexOf(path);
  if (index < 0) return <Default size={19} aria-hidden="true" />;
  return (
    <span className="theme-nav-icon" aria-hidden="true">
      <Default className="nav-icon-default" />
      {Object.entries(variants).map(([style, icons]) => {
        const Icon = icons[index];
        return <Icon key={style} className={`nav-icon-${style}`} />;
      })}
    </span>
  );
}
