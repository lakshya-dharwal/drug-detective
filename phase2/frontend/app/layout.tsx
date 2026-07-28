import type { Metadata } from "next";
import "./globals.css";
import Disclaimer from "@/components/Disclaimer";

export const metadata: Metadata = {
  title: "Drug Detective",
  description:
    "Drug repurposing research tool — ranked candidate drugs for a disease, with evidence breakdowns and source citations. For research only.",
};

// Runs before paint to apply the persisted theme (or OS preference), so there is
// no flash of the wrong theme on first load.
const themeInit = `(function(){try{var t=localStorage.getItem('theme');if(!t){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}if(t==='dark'){document.documentElement.classList.add('dark');}}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInit }} />
      </head>
      <body className="min-h-screen bg-white font-sans text-neutral-900 antialiased dark:bg-black dark:text-neutral-100">
        {children}
        <Disclaimer />
      </body>
    </html>
  );
}
