/**
 * Landing / search — the entire front door. One centered search box, one action.
 * No sidebar, no dashboard. Faint DNA motif as background texture only.
 */
import SearchBox from "@/components/SearchBox";
import AuthButton from "@/components/AuthButton";
import DnaMotif from "@/components/DnaMotif";
import Wordmark from "@/components/Wordmark";
import ThemeToggle from "@/components/ThemeToggle";

export default function Home() {
  return (
    <main className="relative flex min-h-screen flex-col items-center overflow-hidden px-4">
      {/* faint background texture, non-interactive */}
      <div className="pointer-events-none absolute -left-16 top-10 opacity-60">
        <DnaMotif />
      </div>
      <div className="pointer-events-none absolute -right-16 bottom-16 rotate-180 opacity-60">
        <DnaMotif />
      </div>

      <header className="z-10 flex w-full max-w-5xl items-center justify-between py-6">
        <Wordmark size="sm" />
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <AuthButton />
        </div>
      </header>

      <div className="z-10 flex flex-1 flex-col items-center justify-center pb-24 text-center">
        <div className="mb-10">
          <Wordmark />
        </div>
        <h1 className="mb-3 max-w-lg text-balance text-2xl font-semibold text-neutral-900 sm:text-3xl dark:text-neutral-100">
          Find drug repurposing candidates for any disease
        </h1>
        <p className="mb-10 max-w-md text-neutral-500 dark:text-neutral-400">
          Enter a disease to get a ranked list of candidate drugs, each with an
          evidence breakdown and source citations.
        </p>
        <SearchBox />
      </div>
    </main>
  );
}
