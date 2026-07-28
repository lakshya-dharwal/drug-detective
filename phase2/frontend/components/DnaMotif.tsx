/**
 * Subtle, non-interactive DNA double-helix motif.
 * Rendered faint and behind content. `animated` adds a gentle drift used on the
 * progress screen. Never clickable, never cartoonish — pure background texture
 * in the single accent green at low opacity.
 */
export default function DnaMotif({
  animated = false,
  className = "",
}: {
  animated?: boolean;
  className?: string;
}) {
  // Build two sine-offset strands with connecting "rungs".
  const rungs = Array.from({ length: 14 });
  const width = 120;
  const height = 420;

  return (
    <div
      aria-hidden="true"
      className={`pointer-events-none select-none text-accent ${animated ? "animate-helix-drift" : ""} ${className}`}
    >
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        fill="none"
        className="opacity-[0.08] dark:opacity-[0.16]"
      >
        {rungs.map((_, i) => {
          const t = i / (rungs.length - 1);
          const y = t * (height - 20) + 10;
          const phase = t * Math.PI * 3;
          const x1 = width / 2 + Math.sin(phase) * 40;
          const x2 = width / 2 - Math.sin(phase) * 40;
          return (
            <g key={i} stroke="currentColor" strokeWidth={2}>
              <line x1={x1} y1={y} x2={x2} y2={y} strokeWidth={1.4} />
              <circle cx={x1} cy={y} r={3.2} fill="currentColor" stroke="none" />
              <circle cx={x2} cy={y} r={3.2} fill="currentColor" stroke="none" />
            </g>
          );
        })}
      </svg>
    </div>
  );
}
