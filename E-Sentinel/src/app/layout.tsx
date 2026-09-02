import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const fontSans = Geist({
  subsets: ["latin"],
  variable: "--font-sans",
});

const fontMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
});

export const metadata: Metadata = {
  title: "E-Sentinel · 会解释、会认错、会改进的 AI 质量审计员",
  description: "关键词规则会漏掉隐性承诺，E-Sentinel 用证据、规则与人工反馈完成客服质量审计。",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-CN"
      className={`${fontSans.variable} ${fontMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                var theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
                try { theme = localStorage.getItem('e-sentinel-theme') || theme; } catch(e) {}
                document.documentElement.classList.toggle('dark', theme === 'dark');
              })();
            `,
          }}
        />
      </head>
      <body className="min-h-full flex flex-col bg-background font-sans">
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}
