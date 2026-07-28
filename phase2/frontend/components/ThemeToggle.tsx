"use client";

/**
 * Light/dark theme switch. Persists to localStorage and toggles the `.dark`
 * class on <html>. The initial class is set before paint by the inline script
 * in layout.tsx (no flash of the wrong theme).
 *
 * Two-color spirit preserved: the control itself is drawn in the current accent.
 */
import { useEffect, useState } from "react";

function getInitial(): "light" | "dark" {
  if (typeof document !== "undefined") {
    return document.documentElement.classList.contains("dark") ? "dark" : "light";
  }
  return "light";
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setTheme(getInitial());
    setMounted(true);
  }, []);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* ignore storage errors (private mode) */
    }
  }

  const isDark = theme === "dark";

  return (
    <button
      onClick={toggle}
      aria-label={`Switch to ${isDark ? "light" : "dark"} mode`}
      title={`Switch to ${isDark ? "light" : "dark"} mode`}
      className="relative inline-flex h-7 w-12 items-center rounded-full border border-neutral-300 bg-white transition-colors hover:border-accent dark:border-neutral-700 dark:bg-neutral-900"
    >
      {/* knob */}
      <span
        className={`inline-flex h-5 w-5 items-center justify-center rounded-full bg-accent text-white transition-transform dark:text-black ${
          mounted && isDark ? "translate-x-6" : "translate-x-1"
        }`}
      >
        {isDark ? (
          // moon
          <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" />
          </svg>
        ) : (
          // sun
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
            <circle cx="12" cy="12" r="4" />
            <path strokeLinecap="round" d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
          </svg>
        )}
      </span>
    </button>
  );
}
