import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class", "[data-theme='dark']"],
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "var(--c-bg)",
        "bg-elev": "var(--c-bg-elev)",
        "bg-overlay": "var(--c-bg-overlay)",
        fg: "var(--c-fg)",
        "fg-muted": "var(--c-fg-muted)",
        "fg-subtle": "var(--c-fg-subtle)",
        border: "var(--c-border)",
        "border-strong": "var(--c-border-strong)",
        brand: "var(--c-brand)",
        "brand-fg": "var(--c-brand-fg)",
        success: "var(--c-success)",
        warning: "var(--c-warning)",
        danger: "var(--c-danger)",
        info: "var(--c-info)",
        anomaly: "var(--c-anomaly)",
        "trend-up": "var(--c-trend-up)",
        "trend-down": "var(--c-trend-down)",
        refusal: "var(--c-refusal)",
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        pill: "var(--radius-pill)",
      },
      boxShadow: {
        e1: "var(--elev-1)",
        e2: "var(--elev-2)",
        e3: "var(--elev-3)",
        e4: "var(--elev-4)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
        heebo: ["var(--font-heebo)", "var(--font-sans)", "sans-serif"],
      },
      transitionDuration: {
        fast: "var(--dur-fast)",
        DEFAULT: "var(--dur)",
        slow: "var(--dur-slow)",
      },
    },
  },
  plugins: [],
};

export default config;
