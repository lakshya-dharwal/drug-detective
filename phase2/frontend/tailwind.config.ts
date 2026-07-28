import type { Config } from "tailwindcss";

// Drug Detective palette: exactly two colors, per theme.
//   Light:  accent #17A320 (green)  on white  (#FFFFFF)
//   Dark:   accent #26E03A (neon-er green) on black (#000000)
// The accent is driven by CSS variables (see globals.css) so a single class like
// `bg-accent` / `text-accent` swaps automatically when the `.dark` class is set.
// Neutrals are greyscale derivations used sparingly for text/borders.
const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          hover: "rgb(var(--accent-hover) / <alpha-value>)",
          soft: "rgb(var(--accent-soft) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
      keyframes: {
        "helix-drift": {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-8px)" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
      },
      animation: {
        "helix-drift": "helix-drift 6s ease-in-out infinite",
        "fade-up": "fade-up 0.35s ease-out both",
        "pulse-soft": "pulse-soft 1.4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
