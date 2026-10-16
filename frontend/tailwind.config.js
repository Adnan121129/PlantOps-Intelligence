/** Design tokens live in src/index.css as CSS variables; Tailwind maps semantic names onto them. */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        page: v("page"),
        surface: v("surface"),
        raised: v("raised"),
        sunken: v("sunken"),
        border: v("border"),
        "border-strong": v("border-strong"),
        ink: v("ink"),
        "ink-2": v("ink-2"),
        muted: v("muted"),
        accent: v("accent"),
        "accent-ink": v("accent-ink"),
        "accent-soft": v("accent-soft"),
        good: v("good"),
        warn: v("warn"),
        serious: v("serious"),
        bad: v("bad"),
        "good-soft": v("good-soft"),
        "warn-soft": v("warn-soft"),
        "bad-soft": v("bad-soft"),
        info: v("info"),
        "info-soft": v("info-soft"),
      },
      fontFamily: { sans: ['system-ui', '-apple-system', '"Segoe UI"', "Roboto", "sans-serif"] },
      fontSize: { "2xs": ["0.6875rem", "1rem"] },
      boxShadow: { card: "0 1px 2px rgb(0 0 0 / 0.04)", pop: "0 8px 24px rgb(0 0 0 / 0.14)" },
    },
  },
  plugins: [],
};
