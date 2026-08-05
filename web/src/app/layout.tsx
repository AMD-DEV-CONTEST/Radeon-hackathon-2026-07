import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";


const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://pitchdock.xyz"),
  title: {
    default: "PitchDock | AI Recruiter Outreach & Cold Email Automator",
    template: "%s | PitchDock"
  },
  description: "Skip the ATS filters. PitchDock writes highly personalized, AI-tailored cold emails to recruiters, attaches your resume PDF, and staggers delivery to safely land you interviews.",
  keywords: [
    "cold email outreach",
    "recruiter outreach",
    "AI job hunt",
    "ATS bypass",
    "personalized job application",
    "automated cold emailing",
    "software engineer jobs",
    "job application automation",
    "PitchDock"
  ],
  authors: [{ name: "PitchDock Team" }],
  creator: "PitchDock Team",
  publisher: "PitchDock",
  formatDetection: {
    email: false,
    address: false,
    telephone: false,
  },
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "https://pitchdock.xyz",
    siteName: "PitchDock",
    title: "PitchDock | AI Recruiter Outreach & Cold Email Automator",
    description: "Skip the ATS filters. PitchDock writes highly personalized, AI-tailored cold emails to recruiters, attaches your resume PDF, and staggers delivery to safely land you interviews.",
    images: [
      {
        url: "/og-image.jpg",
        width: 1200,
        height: 630,
        alt: "PitchDock - Reach the recruiter, not the filter"
      }
    ]
  },
  twitter: {
    card: "summary_large_image",
    title: "PitchDock | AI Recruiter Outreach & Cold Email Automator",
    description: "Personalized AI outreach to land job interviews.",
    creator: "@pitchdock",
    images: ["/og-image.jpg"]
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-video-preview': -1,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
  icons: {
    icon: "/orangelogo_circle.png",
    shortcut: "/orangelogo_circle.png",
    apple: "/orangelogo_circle.png",
  }
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body>
        {children}
      </body>
    </html>
  );
}

