"use client";

import Link from "next/link";
import Navbar from "@/components/Navbar";

export default function PrivacyPage() {
  return (
    <>
      <div className="grid-backdrop"></div>
      <Navbar />

      <div style={{ padding: "140px 24px 80px 24px", maxWidth: "800px", margin: "0 auto", color: "var(--text)", lineHeight: "1.6", position: "relative", zIndex: 2 }}>
        <Link href="/" style={{ fontSize: "14px", color: "var(--signal-soft)", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: "6px", marginBottom: "32px", fontWeight: 500, fontFamily: "var(--font-mono)" }}>
          ← Back to PitchDock Homepage
        </Link>

        <h1 style={{ fontFamily: "var(--font-display)", fontSize: "36px", fontWeight: "700", marginBottom: "8px", letterSpacing: "-0.5px", color: "var(--text)" }}>Privacy Policy</h1>
        <p style={{ color: "var(--text-muted)", fontSize: "14px", marginBottom: "40px", fontFamily: "var(--font-mono)" }}>Last Updated: July 20, 2026</p>

        <div style={{ display: "flex", flexDirection: "column", gap: "32px" }}>
          <section>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "12px", color: "var(--text)", fontFamily: "var(--font-display)" }}>1. Information We Collect</h2>
            <p style={{ color: "var(--text-muted)" }}>
              We collect information you provide directly to us when creating an account, setting up your profile, or contacting us. This includes:
            </p>
            <ul style={{ paddingLeft: "20px", margin: "10px 0", display: "flex", flexDirection: "column", gap: "8px", color: "var(--text-muted)" }}>
              <li><strong style={{ color: "var(--text)" }}>Account Data:</strong> Name, email address, password hash, and sign-up dates.</li>
              <li><strong style={{ color: "var(--text)" }}>Outreach Profile:</strong> Professional details, work history achievements, educational credentials, target titles, and resume PDF files.</li>
              <li><strong style={{ color: "var(--text)" }}>Outreach Configurations:</strong> Custom SMTP credentials (host, port, sender email, app passwords) to route dispatches directly through your mailbox.</li>
            </ul>
          </section>

          <section>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "12px", color: "var(--text)", fontFamily: "var(--font-display)" }}>2. How We Use Your Information</h2>
            <p style={{ color: "var(--text-muted)" }}>
              We use the collected information for the following purposes:
            </p>
            <ul style={{ paddingLeft: "20px", margin: "10px 0", display: "flex", flexDirection: "column", gap: "8px", color: "var(--text-muted)" }}>
              <li>To personalize and write custom cold email drafts using our AI models based on your background and the targeted recruiter.</li>
              <li>To deliver the emails through your configured SMTP mail server safely.</li>
              <li>To manage and track subscription usage quotas and billing transaction receipts.</li>
              <li>To answer your support tickets, refund requests, or feedback inputs.</li>
            </ul>
          </section>

          <section>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "12px", color: "var(--text)", fontFamily: "var(--font-display)" }}>3. Data Sharing and Third-Party API Integrations</h2>
            <p style={{ color: "var(--text-muted)" }}>
              We do not sell, trade, or rent your personal profile information to third parties. We share information with service providers strictly necessary to run the platform:
            </p>
            <ul style={{ paddingLeft: "20px", margin: "10px 0", display: "flex", flexDirection: "column", gap: "8px", color: "var(--text-muted)" }}>
              <li><strong style={{ color: "var(--text)" }}>AI Models:</strong> Recruiter titles and candidate profile achievements are processed via secured Large Language Model (LLM) APIs to generate drafts.</li>
              <li><strong style={{ color: "var(--text)" }}>Payment Gateways:</strong> Transaction tokens are processed securely by our PCI-DSS compliant checkout systems.</li>
            </ul>
          </section>

          <section style={{ background: "var(--signal-dim)", borderLeft: "4px solid var(--signal)", padding: "16px 20px", borderRadius: "0 8px 8px 0" }}>
            <h2 style={{ fontSize: "18px", fontWeight: "600", marginBottom: "8px", color: "var(--signal-soft)", fontFamily: "var(--font-display)" }}>Google User Data & Limited Use Disclosure</h2>
            <p style={{ fontSize: "14px", marginBottom: "8px", color: "var(--text)" }}>
              PitchDock uses Google OAuth to allow users to send cold email outreach dispatches directly via Google API (Gmail). We only access your Google account to send emails explicitly requested by you and to identify your connected email address.
            </p>
            <p style={{ fontSize: "14px", fontWeight: "500", color: "var(--text)" }}>
              PitchDock's use and transfer to any other app of information received from Google APIs will adhere to the <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noopener noreferrer" style={{ color: "var(--signal-soft)", textDecoration: "underline" }}>Google API Services User Data Policy</a>, including the Limited Use requirements.
            </p>
          </section>

          <section>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "12px", color: "var(--text)", fontFamily: "var(--font-display)" }}>4. Security</h2>
            <p style={{ color: "var(--text-muted)" }}>
              We implement industry-standard encryption to protect your sensitive authentication tokens and SMTP configuration data both in transit and at rest.
            </p>
          </section>

          <section>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "12px", color: "var(--text)", fontFamily: "var(--font-display)" }}>5. Contact Us</h2>
            <p style={{ color: "var(--text-muted)" }}>
              If you have any questions regarding this Privacy Policy, please contact our support team at <a href="mailto:support@pitchdock.xyz" style={{ color: "var(--signal-soft)", textDecoration: "underline" }}>support@pitchdock.xyz</a>.
            </p>
          </section>
        </div>
      </div>
    </>
  );
}
