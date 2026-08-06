import type { Metadata } from 'next';
import { cookies } from 'next/headers';
import { Outfit, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import Nav from '@/components/Nav';
import { LanguageProvider } from '@/components/LanguageProvider';
import { ThemeProvider } from '@/components/ThemeProvider';
import CommandPalette from '@/components/CommandPalette';
import type { Lang } from '@/lib/i18n';

// ─── Font optimization: next/font eliminates render-blocking <link> tags ──────
// Fonts are self-hosted at build time, served from the same origin, and
// loaded with display:'swap' so text renders immediately with fallback.
const outfit = Outfit({
  subsets: ['latin'],
  weight: ['300', '400', '500', '600', '700', '800'],
  display: 'swap',
  variable: '--font-outfit',
  preload: true,
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  display: 'optional',   // mono is non-critical; only swap in if loaded fast
  variable: '--font-jetbrains-mono',
  preload: false,
});

export const metadata: Metadata = {
  title: 'Solo Worker OS',
  description: 'A one-person business operating system powered by AI.',
  keywords: ['freelance', 'solo', 'AI assistant', 'project management', 'invoicing'],
  openGraph: {
    title: 'Solo Worker OS',
    description: 'Manage your freelance business through natural conversation.',
    type: 'website',
  },
};

// Inline script — runs before paint to prevent theme flash (FOUC)
const themeScript = `
(function() {
  try {
    var t = localStorage.getItem('solo-theme');
    if (t === 'dark') document.documentElement.classList.add('dark');
  } catch(e) {}
})();
`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = cookies();
  const rawLang = cookieStore.get('solo-lang')?.value;
  const initialLang: Lang = rawLang === 'en' ? 'en' : 'zh';

  return (
    <html lang={initialLang} className={`scroll-smooth ${outfit.variable} ${jetbrainsMono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen font-sans antialiased">
        <ThemeProvider>
          <LanguageProvider initialLang={initialLang}>
            <Nav />
            <main className="relative z-10 mx-auto max-w-[1400px] px-4 py-8 sm:px-6 lg:px-8">
              {children}
            </main>
            <CommandPalette />
          </LanguageProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
