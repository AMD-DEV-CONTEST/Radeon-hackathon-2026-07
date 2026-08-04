import type { Metadata } from "next";
import "./globals.css";
import { RadialMenu } from "@/components/layout/RadialMenu";

export const metadata: Metadata = {
  title: "LaunchKart AI 2.0 | AMD E-commerce Platform",
  description: "Autonomous AI E-commerce Team powered by AMD Radeon GPUs",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased min-h-screen bg-[var(--color-background)] text-[var(--color-foreground)]">
        {children}
        <RadialMenu />
      </body>
    </html>
  );
}

