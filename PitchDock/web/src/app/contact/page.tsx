"use client";

import { useState } from "react";
import Link from "next/link";
import Navbar from "@/components/Navbar";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://www.pitchdock.xyz";

export default function ContactPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [subject, setSubject] = useState("General Query");
  const [message, setMessage] = useState("");
  const [success, setSuccess] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !email.trim() || !message.trim()) return;
    setIsSubmitting(true);
    setError("");
    setSuccess("");
    try {
      const res = await fetch(`${API_BASE}/api/support`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, subject, message })
      });
      if (res.ok) {
        setSuccess("Your support inquiry was successfully sent. The PitchDock team will email you back shortly!");
        setName("");
        setEmail("");
        setMessage("");
      } else {
        const data = await res.json();
        setError(data.detail || "Failed to deliver support inquiry.");
      }
    } catch (err) {
      setError("Unable to connect to the mail server. Please try again later.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <div className="grid-backdrop"></div>
      <Navbar />

      <div style={{ padding: "140px 24px 80px 24px", maxWidth: "900px", margin: "0 auto", color: "var(--text)", lineHeight: "1.6", position: "relative", zIndex: 2 }}>
        <Link href="/" style={{ fontSize: "14px", color: "var(--signal-soft)", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: "6px", marginBottom: "32px", fontWeight: 500, fontFamily: "var(--font-mono)" }}>
          ← Back to PitchDock Homepage
        </Link>

        <h1 style={{ fontFamily: "var(--font-display)", fontSize: "36px", fontWeight: "700", marginBottom: "8px", letterSpacing: "-0.5px", color: "var(--text)" }}>Contact Us</h1>
        <p style={{ color: "var(--text-muted)", fontSize: "14.5px", marginBottom: "40px" }}>Get in touch with the PitchDock developers for queries, technical setup, or refund requests.</p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: "48px", marginTop: "20px" }}>
          
          {/* Left Column: Coordinates */}
          <div>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "20px", color: "var(--text)", fontFamily: "var(--font-display)" }}>Support Coordinates</h2>
            
            <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
              <div style={{ background: "var(--surface)", border: "1px solid var(--border)", padding: "20px", borderRadius: "12px" }}>
                <h3 style={{ fontSize: "14px", fontWeight: "600", textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-dim)", marginBottom: "6px", fontFamily: "var(--font-mono)" }}>Email Inquiry</h3>
                <p style={{ fontSize: "15px", fontWeight: "500", color: "var(--text)" }}>support@pitchdock.xyz</p>
                <p style={{ fontSize: "13px", color: "var(--text-muted)", marginTop: "4px" }}>Response time: Usually within 24 hours</p>
              </div>

              <div style={{ background: "var(--surface)", border: "1px solid var(--border)", padding: "20px", borderRadius: "12px" }}>
                <h3 style={{ fontSize: "14px", fontWeight: "600", textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-dim)", marginBottom: "6px", fontFamily: "var(--font-mono)" }}>Developer Operations</h3>
                <p style={{ fontSize: "15px", fontWeight: "500", color: "var(--text)" }}>PitchDock Engineering Team</p>
                <p style={{ fontSize: "13px", color: "var(--text-muted)", marginTop: "4px" }}>Bengaluru & Remote, India</p>
              </div>
            </div>
          </div>

          {/* Right Column: Interactive Support Form */}
          <div style={{ background: "var(--surface)", border: "1px solid var(--border-strong)", borderRadius: "16px", padding: "28px", boxShadow: "0 10px 30px rgba(0,0,0,0.4)" }}>
            <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "16px", color: "var(--text)", fontFamily: "var(--font-display)" }}>Send a Direct Query</h2>
            
            {success && (
              <div style={{ background: "rgba(87,217,163,0.1)", border: "1px solid var(--good)", color: "var(--good)", padding: "12px 16px", borderRadius: "8px", fontSize: "13.5px", marginBottom: "20px" }}>
                {success}
              </div>
            )}

            {error && (
              <div style={{ background: "rgba(255,90,46,0.1)", border: "1px solid var(--signal)", color: "var(--signal-soft)", padding: "12px 16px", borderRadius: "8px", fontSize: "13.5px", marginBottom: "20px" }}>
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <div>
                <label style={{ fontSize: "12px", fontFamily: "var(--font-mono)", color: "var(--text-muted)", display: "block", marginBottom: "6px" }}>Your Full Name</label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Alex Mercer"
                  style={{ width: "100%", padding: "10px 14px", borderRadius: "8px", background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", color: "var(--text)", outline: "none", fontSize: "14px" }}
                />
              </div>

              <div>
                <label style={{ fontSize: "12px", fontFamily: "var(--font-mono)", color: "var(--text-muted)", display: "block", marginBottom: "6px" }}>Email Address</label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="alex@example.com"
                  style={{ width: "100%", padding: "10px 14px", borderRadius: "8px", background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", color: "var(--text)", outline: "none", fontSize: "14px" }}
                />
              </div>

              <div>
                <label style={{ fontSize: "12px", fontFamily: "var(--font-mono)", color: "var(--text-muted)", display: "block", marginBottom: "6px" }}>Inquiry Category</label>
                <select
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  style={{ width: "100%", padding: "10px 14px", borderRadius: "8px", background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", color: "var(--text)", outline: "none", fontSize: "14px" }}
                >
                  <option value="General Query">General Query</option>
                  <option value="Technical Support">Technical Support / Custom SMTP Setup</option>
                  <option value="Billing & Refunds">Billing & Refund Request</option>
                  <option value="Partnership">Partnership Inquiry</option>
                </select>
              </div>

              <div>
                <label style={{ fontSize: "12px", fontFamily: "var(--font-mono)", color: "var(--text-muted)", display: "block", marginBottom: "6px" }}>Message</label>
                <textarea
                  rows={4}
                  required
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Tell us how we can help your outreach campaign..."
                  style={{ width: "100%", padding: "10px 14px", borderRadius: "8px", background: "var(--bg-elevated)", border: "1px solid var(--border-strong)", color: "var(--text)", outline: "none", fontSize: "14px", resize: "none" }}
                ></textarea>
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="btn btn-primary btn-block"
                style={{ marginTop: "6px" }}
              >
                {isSubmitting ? "Sending..." : "Submit Inquiry →"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </>
  );
}
