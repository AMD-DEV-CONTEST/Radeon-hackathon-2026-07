import type { Metadata } from "next";
import "./globals.css";
import { TopBar } from "./TopBar";

export const metadata: Metadata = {
  title: "Aegis — Autonomous Incident Commander",
  description: "Multi-agent, on-prem incident investigation running on AMD ROCm.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <TopBar />
          {children}
        </div>
      </body>
    </html>
  );
}
