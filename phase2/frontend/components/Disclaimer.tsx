/**
 * Persistent, unobtrusive research-only disclaimer. Always visible, fixed to the
 * bottom, never dismissible.
 */
export default function Disclaimer() {
  return (
    <div className="fixed bottom-0 inset-x-0 z-40 border-t border-neutral-200 bg-white/90 backdrop-blur-sm dark:border-neutral-800 dark:bg-black/90">
      <p className="mx-auto max-w-5xl px-4 py-2 text-center text-[11px] tracking-wide text-neutral-500 dark:text-neutral-400">
        For research purposes only. Not medical advice.
      </p>
    </div>
  );
}
