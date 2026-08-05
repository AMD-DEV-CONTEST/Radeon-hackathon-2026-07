"use client";

import { useState, useEffect, Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

function VerifyEmailContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("Verifying your email address...");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("Verification token is missing. Please check your verification link.");
      return;
    }

    const verifyToken = async () => {
      try {
        const response = await fetch(`/api/auth/verify?token=${token}`, {
          method: "GET",
          credentials: "include"
        });

        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || "Failed to verify account.");
        }

        setStatus("success");
        setMessage("Account verified successfully! Redirecting to your console...");
        
        // Save the authenticated session details
        localStorage.setItem("authToken", data.token);
        localStorage.setItem("authUser", JSON.stringify(data.user));

        // Auto-redirect to dashboard after 2.5 seconds
        setTimeout(() => {
          router.push("/dashboard");
        }, 2500);

      } catch (err: any) {
        setStatus("error");
        setMessage(err.message || "Invalid or expired verification token.");
      }
    };

    verifyToken();
  }, [token, router]);

  return (
    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "116px 20px 40px" }}>
      <div style={{
        width: "100%",
        maxWidth: "420px",
        backgroundColor: "#ffffff",
        border: "1px solid rgba(24, 24, 27, 0.08)",
        borderRadius: "16px",
        padding: "36px",
        boxShadow: "0 4px 20px rgba(24, 24, 27, 0.02)",
        textAlign: "center"
      }}>
        <img 
          src="/orangelogo.png" 
          alt="PitchDock Logo" 
          style={{ display: "block", margin: "0 auto 16px", width: "48px", height: "48px", borderRadius: "50%", objectFit: "cover" }} 
        />

        {status === "loading" && (
          <div>
            <div style={{
              width: "48px",
              height: "48px",
              borderRadius: "50%",
              border: "3px solid rgba(24, 24, 27, 0.08)",
              borderTopColor: "var(--ink)",
              animation: "spin 1s linear infinite",
              margin: "24px auto 16px"
            }}></div>
            <h1 style={{ fontFamily: "var(--font-space-grotesk)", fontSize: "22px", fontWeight: 700, color: "var(--text-primary)", marginBottom: "8px" }}>
              Verifying account
            </h1>
            <p style={{ fontSize: "14px", color: "var(--text-secondary)", lineHeight: "1.5" }}>
              {message}
            </p>
          </div>
        )}

        {status === "success" && (
          <div>
            <div style={{
              width: "48px",
              height: "48px",
              borderRadius: "50%",
              backgroundColor: "rgba(16, 185, 129, 0.08)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "24px auto 16px"
            }}>
              <svg style={{ width: "24px", height: "24px", color: "#10B981" }} fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
            </div>
            <h1 style={{ fontFamily: "var(--font-space-grotesk)", fontSize: "22px", fontWeight: 700, color: "var(--text-primary)", marginBottom: "8px" }}>
              Verification Success!
            </h1>
            <p style={{ fontSize: "14px", color: "var(--text-secondary)", lineHeight: "1.5" }}>
              {message}
            </p>
          </div>
        )}

        {status === "error" && (
          <div>
            <div style={{
              width: "48px",
              height: "48px",
              borderRadius: "50%",
              backgroundColor: "rgba(239, 68, 68, 0.08)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "24px auto 16px"
            }}>
              <svg style={{ width: "24px", height: "24px", color: "#EF4444" }} fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <h1 style={{ fontFamily: "var(--font-space-grotesk)", fontSize: "22px", fontWeight: 700, color: "var(--text-primary)", marginBottom: "8px" }}>
              Verification Failed
            </h1>
            <p style={{ fontSize: "14px", color: "var(--accent-red)", lineHeight: "1.5", marginBottom: "24px" }}>
              {message}
            </p>
            <Link href="/login" className="btn btn-primary" style={{ width: "100%", justifyContent: "center" }}>
              Go to Sign in
            </Link>
          </div>
        )}
      </div>

      <style jsx global>{`
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <div className="landing-root landing-page-wrapper" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <Suspense fallback={
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "116px 20px 40px" }}>
          <div style={{ fontSize: "15px", color: "var(--text-secondary)" }}>Loading verification environment...</div>
        </div>
      }>
        <VerifyEmailContent />
      </Suspense>
    </div>
  );
}
