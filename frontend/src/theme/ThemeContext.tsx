import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";
export const THEME_KEY = "plantops.theme";

interface ThemeState {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (p: ThemePreference) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeState | null>(null);

function systemTheme(): ResolvedTheme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function readStored(): ThemePreference {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "system";
  } catch {
    return "system";
  }
}

export function ThemeProvider({ children, onChange }: { children: ReactNode; onChange?: (p: ThemePreference) => void }) {
  const [preference, setPref] = useState<ThemePreference>(readStored);
  const [system, setSystem] = useState<ResolvedTheme>(systemTheme);
  const resolved: ResolvedTheme = preference === "system" ? system : preference;

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const listener = () => setSystem(mq.matches ? "dark" : "light");
    mq.addEventListener?.("change", listener);
    return () => mq.removeEventListener?.("change", listener);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolved);
  }, [resolved]);

  const setPreference = useCallback((p: ThemePreference) => {
    setPref(p);
    try {
      localStorage.setItem(THEME_KEY, p);
    } catch {
      /* storage unavailable: preference lasts for this session only */
    }
    onChange?.(p);
  }, [onChange]);

  const toggle = useCallback(() => setPreference(resolved === "dark" ? "light" : "dark"), [resolved, setPreference]);
  const value = useMemo(() => ({ preference, resolved, setPreference, toggle }), [preference, resolved, setPreference, toggle]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside ThemeProvider");
  return ctx;
}

/**
 * Chart palette (validated with the dataviz validator against #fcfcfb / #1a1a19 surfaces;
 * light-mode slots 3-5 are below 3:1 contrast, so every chart ships a legend and a table view).
 */
export const CHART = {
  light: {
    series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    grid: "#e1e0d9", axis: "#c3c2b7", tick: "#706f69", surface: "#ffffff", ink: "#111211",
    target: "#52514e", muted: "#a8a69e",
  },
  dark: {
    series: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
    grid: "#2c2c2a", axis: "#383835", tick: "#9a988f", surface: "#1a1a19", ink: "#f0efec",
    target: "#c3c2b7", muted: "#5d5c57",
  },
  status: { good: "#0ca30c", warning: "#fab219", serious: "#ec835a", critical: "#d03b3b" },
} as const;

export function useChartColors() {
  const { resolved } = useTheme();
  return { ...CHART[resolved], status: CHART.status };
}
