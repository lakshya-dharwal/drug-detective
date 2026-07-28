/**
 * "Drug Detective" wordmark. Two-color only: neutral text with the accent green
 * on the second word plus a small magnifier-over-molecule glyph.
 */
export default function Wordmark({ size = "lg" }: { size?: "lg" | "sm" }) {
  const text = size === "lg" ? "text-3xl" : "text-lg";
  const glyph = size === "lg" ? 26 : 20;
  return (
    <div className="flex items-center gap-2">
      <svg width={glyph} height={glyph} viewBox="0 0 24 24" fill="none" aria-hidden="true" className="text-accent">
        {/* molecule */}
        <circle cx="9" cy="9" r="2.4" fill="currentColor" />
        <circle cx="15" cy="7" r="1.7" fill="currentColor" opacity="0.6" />
        <line x1="9" y1="9" x2="15" y2="7" stroke="currentColor" strokeWidth="1.3" />
        {/* magnifier */}
        <circle cx="11" cy="12" r="6.2" stroke="currentColor" strokeWidth="1.8" />
        <line x1="16" y1="17" x2="21" y2="22" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      </svg>
      <span className={`${text} font-bold tracking-tight`}>
        <span className="text-neutral-900 dark:text-white">Drug</span>{" "}
        <span className="text-accent">Detective</span>
      </span>
    </div>
  );
}
