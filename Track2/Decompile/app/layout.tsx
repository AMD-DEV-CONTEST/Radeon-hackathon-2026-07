import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Decompile — Video to software",
  description: "Turn any YouTube video into production-ready software."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
