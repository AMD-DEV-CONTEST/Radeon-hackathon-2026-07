"use client";

import Link from "next/link";
import Navbar from "@/components/Navbar";

export default function TermsPage() {
  return (
    <>
      <div className="grid-backdrop"></div>
      <Navbar />

      <div style={{ padding: "140px 24px 80px 24px", maxWidth: "800px", margin: "0 auto", color: "var(--text)", lineHeight: "1.6", position: "relative", zIndex: 2 }}>
        <Link href="/" style={{ fontSize: "14px", color: "var(--signal-soft)", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: "6px", marginBottom: "32px", fontWeight: 500, fontFamily: "var(--font-mono)" }}>
          ← Back to PitchDock Homepage
        </Link>

        <h1 style={{ fontFamily: "var(--font-display)", fontSize: "36px", fontWeight: "700", marginBottom: "8px", letterSpacing: "-0.5px", color: "var(--text)" }}>Terms & Conditions</h1>
        <p style={{ color: "var(--text-muted)", fontSize: "14px", marginBottom: "40px", fontFamily: "var(--font-mono)" }}>Last Updated: July 20, 2026</p>

        <div style={{ display: "flex", flexDirection: "column", gap: "32px" }}>
          <section>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "12px", color: "var(--text)", fontFamily: "var(--font-display)" }}>1. Acceptance of Terms</h2>
            <p style={{ color: "var(--text-muted)" }}>
              By accessing or using PitchDock (available at pitchdock.xyz), you agree to be bound by these Terms and Conditions. If you do not agree to all of these terms, please do not use our website or services.
            </p>
          </section>

          <section>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "12px", color: "var(--text)", fontFamily: "var(--font-display)" }}>2. Description of Service</h2>
            <p style={{ color: "var(--text-muted)" }}>
              PitchDock is an AI-powered outreach automator designed to help job candidates generate personalized cold email drafts to recruiters and manage delivery pipelines. You are responsible for configuring your sender credentials (via custom SMTP server connection), providing your resume, and selecting target company outreach tiers.
            </p>
          </section>

          <section>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "12px", color: "var(--text)", fontFamily: "var(--font-display)" }}>3. User Accounts and Responsibility</h2>
            <p style={{ color: "var(--text-muted)" }}>
              To use certain features, you must sign up for an account. You represent that the email account connected for SMTP outreach belongs to you and that you have all necessary rights to send emails from that address. You agree not to use PitchDock to:
            </p>
            <ul style={{ paddingLeft: "20px", margin: "10px 0", display: "flex", flexDirection: "column", gap: "8px", color: "var(--text-muted)" }}>
              <li>Send spam, unsolicited advertisements, or bulk messaging violating local anti-spam regulations.</li>
              <li>Transmit content that is unlawful, harmful, threatening, abusive, defamatory, or otherwise objectionable.</li>
              <li>Impersonate any person or entity, or falsely state your affiliation with an organization.</li>
            </ul>
          </section>

          <section>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "12px", color: "var(--text)", fontFamily: "var(--font-display)" }}>4. Billing, Subscriptions, and Payments</h2>
            <p style={{ color: "var(--text-muted)" }}>
              Certain services are offered on a paid subscription basis (Basic, Standard, or Premium). 
            </p>
            <ul style={{ paddingLeft: "20px", margin: "10px 0", display: "flex", flexDirection: "column", gap: "8px", color: "var(--text-muted)" }}>
              <li>All fees are billed in advance on a recurring monthly or annual basis depending on your plan.</li>
              <li>Payments are processed securely via our payment gateway providers.</li>
              <li>You agree to keep your billing information up to date to prevent subscription suspension.</li>
            </ul>
          </section>

          <section>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "12px", color: "var(--text)", fontFamily: "var(--font-display)" }}>5. Limitation of Liability</h2>
            <p style={{ color: "var(--text-muted)" }}>
              PitchDock, its developers, and affiliates shall not be liable for any indirect, incidental, special, consequential, or punitive damages. We do not guarantee job interview callbacks, job offers, or that your custom SMTP emails will not land in spam folders. The service is provided on an "as is" and "as available" basis.
            </p>
          </section>

          <section>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "12px", color: "var(--text)", fontFamily: "var(--font-display)" }}>6. Governing Law</h2>
            <p style={{ color: "var(--text-muted)" }}>
              These Terms shall be governed and construed in accordance with local laws, without regard to its conflict of law provisions.
            </p>
          </section>
        </div>
      </div>
    </>
  );
}
