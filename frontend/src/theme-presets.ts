import {
  defaultAppearance,
  type Appearance,
  type ThemeStyle,
} from "./appearance";

export type ThemePreset = {
  id: ThemeStyle;
  name: string;
  description: string;
  value: Appearance | null;
};
export const themePresets: ThemePreset[] = [
  {
    id: "classic",
    name: "MediaHub Classic",
    description: "The familiar MediaHub look.",
    value: null,
  },
  {
    id: "midnight-glass",
    name: "Midnight Glass",
    description: "Smoked navy glass, cyan edges and a calm glow.",
    value: {
      ...defaultAppearance,
      style: "midnight-glass",
      mode: "dark",
      accent: "#25d5f5",
      secondary: "#8d9cff",
      background: "#173b60",
      depth: 42,
    },
  },
  {
    id: "soft-orbit",
    name: "Soft Orbit",
    description: "Pearl surfaces, lavender and soft rounded cards.",
    value: {
      ...defaultAppearance,
      style: "soft-orbit",
      mode: "light",
      accent: "#7961d9",
      secondary: "#7968b3",
      background: "#726594",
      depth: 12,
    },
  },
  {
    id: "precision-terminal",
    name: "Precision Terminal",
    description: "Matte graphite, mint and precise compact details.",
    value: {
      ...defaultAppearance,
      style: "precision-terminal",
      mode: "dark",
      density: "compact",
      accent: "#7ce3b6",
      secondary: "#88c8cc",
      background: "#242a28",
      depth: 24,
    },
  },
  {
    id: "floating-layers",
    name: "Floating Layers",
    description: "Slate layers, blue accents and gentle depth.",
    value: {
      ...defaultAppearance,
      style: "floating-layers",
      mode: "dark",
      accent: "#79aaff",
      secondary: "#b1a2ff",
      background: "#29354c",
      depth: 57,
    },
  },
  {
    id: "edge-signal",
    name: "Edge Signal",
    description: "Neutral charcoal, amber accents and crisp edges.",
    value: {
      ...defaultAppearance,
      style: "edge-signal",
      mode: "dark",
      accent: "#f5bd59",
      secondary: "#d5ac80",
      background: "#282828",
      depth: 30,
    },
  },
];
