import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { THEME_KEY, ThemeProvider, useTheme } from "@/theme/ThemeContext";
import { ThemeToggle } from "@/components/layout/AppShell";

function Probe() {
  const { preference, resolved } = useTheme();
  return <p data-testid="probe">{preference}/{resolved}</p>;
}

describe("theme system", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("toggles between light and dark, sets data-theme and persists the choice", async () => {
    const onChange = vi.fn();
    render(<MemoryRouter><ThemeProvider onChange={onChange}><ThemeToggle /><Probe /></ThemeProvider></MemoryRouter>);
    expect(screen.getByTestId("probe")).toHaveTextContent("system/light");
    await userEvent.click(screen.getByRole("button", { name: /switch to dark theme/i }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(onChange).toHaveBeenCalledWith("dark");
    await userEvent.click(screen.getByRole("button", { name: /switch to light theme/i }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem(THEME_KEY)).toBe("light");
  });

  it("restores the persisted preference on a new session", () => {
    localStorage.setItem(THEME_KEY, "dark");
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId("probe")).toHaveTextContent("dark/dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("follows the operating-system setting when preference is 'system'", () => {
    const listeners: ((e: MediaQueryListEvent) => void)[] = [];
    const mq = { matches: true, addEventListener: (_: string, l: (e: MediaQueryListEvent) => void) => listeners.push(l), removeEventListener: () => undefined };
    const original = window.matchMedia;
    window.matchMedia = (() => mq) as unknown as typeof window.matchMedia;
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId("probe")).toHaveTextContent("system/dark");
    mq.matches = false;
    act(() => listeners.forEach((l) => l({} as MediaQueryListEvent)));
    expect(screen.getByTestId("probe")).toHaveTextContent("system/light");
    window.matchMedia = original;
  });
});
