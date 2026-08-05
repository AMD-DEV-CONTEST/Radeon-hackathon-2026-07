import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Outfit } from "next/font/google";
import "./globals.css";

/**
 * Fonts are SELF-HOSTED, deliberately.
 *
 * globals.css used to open with
 * `@import url("https://fonts.googleapis.com/css2?family=...")` and there was no
 * `next/font` anywhere and no vendored font file anywhere -- that CDN import was
 * the app's only source of type. Two consequences, both bad for this product
 * specifically:
 *
 *   1. It is a network request on every single launch, to Google, from an
 *      application whose central claim is local-first privacy sovereignty. A
 *      user who sets the network policy to "offline" was still announcing every
 *      app start to a third party before rendering a single pixel.
 *   2. When that request fails -- offline, air-gapped, blocked, or just a slow
 *      link -- the UI silently falls back to system fonts. The design was never
 *      guaranteed to be what shipped.
 *
 * `next/font/google` downloads these at BUILD time and serves them from the
 * app's own origin, so there is no runtime request and no third-party
 * dependency in the shipped bundle. The CSS variable names match what
 * globals.css already referenced (`--font-inter` etc.), which were declared and
 * never populated.
 */
const inter = Inter({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "700", "800"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

const outfit = Outfit({
  subsets: ["latin"],
  weight: ["300", "400", "500", "700", "900"],
  variable: "--font-outfit",
  display: "swap",
});
import { DeterminexErrorBoundary } from "@/components/DeterminexErrorBoundary";
import { IterationThemeProvider } from "@/contexts/IterationThemeContext";
import { SettingsProvider } from "@/contexts/SettingsContext";
import { AiRouterProvider } from "@/contexts/AiRouterContext";
import { ToastProvider } from "@/components/ErrorToast";
import { PolicyBlockProvider } from "@/components/PolicyBlockProvider";

export const metadata: Metadata = {
  title: "Determinex — AI Pack Orchestration Platform",
  description:
    "A local-first, multi-model AI orchestration IDE for autonomous code generation, context management, and pack-based reasoning.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`h-full antialiased ${inter.variable} ${jetbrainsMono.variable} ${outfit.variable}`}
    >
      <body className="min-h-full flex flex-col">
        <IterationThemeProvider>
          <ToastProvider>
            <SettingsProvider>
              <AiRouterProvider>
                <PolicyBlockProvider>
                  <DeterminexErrorBoundary>{children}</DeterminexErrorBoundary>
                </PolicyBlockProvider>
              </AiRouterProvider>
            </SettingsProvider>
          </ToastProvider>
        </IterationThemeProvider>
      </body>
    </html>
  );
}
