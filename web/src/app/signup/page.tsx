"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [isRegistered, setIsRegistered] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("authToken");
    if (token) {
      router.push("/dashboard");
    }
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    if (password.length < 6) {
      setError("Password must be at least 6 characters long.");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
        credentials: "include"
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Failed to sign up");
      }

      if (data.requires_verification) {
        setIsRegistered(true);
      } else {
        localStorage.setItem("authToken", data.token);
        localStorage.setItem("authUser", JSON.stringify(data.user));
        router.push("/dashboard");
      }
    } catch (err: any) {
      setError(err.message || "Failed to register user. Email might already be taken.");
    } finally {
      setLoading(false);
    }
  };

  if (isRegistered) {
    return (
      <>
        <div className="grid-backdrop"></div>

        <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: "40px 20px" }}>
          <div style={{
            width: "100%",
            maxWidth: "420px",
            backgroundColor: "var(--surface)",
            border: "1px solid var(--border-strong)",
            borderRadius: "18px",
            padding: "36px",
            boxShadow: "0 20px 50px rgba(0,0,0,0.6)",
            textAlign: "center",
            position: "relative",
            zIndex: 2
          }}>
            <img 
              src="/orangelogo.png" 
              alt="PitchDock Logo" 
              style={{ display: "block", margin: "0 auto 16px", width: "52px", height: "52px", borderRadius: "50%", objectFit: "cover", boxShadow: "0 0 20px rgba(255, 90, 46, 0.3)" }} 
            />
            <div style={{
              width: "48px",
              height: "48px",
              borderRadius: "50%",
              backgroundColor: "rgba(87, 217, 163, 0.1)",
              border: "1px solid var(--good)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "24px auto 16px"
            }}>
              <svg style={{ width: "24px", height: "24px", color: "var(--good)" }} fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
            </div>
            
            <h1 style={{ fontFamily: "var(--font-display)", fontSize: "24px", fontWeight: 700, color: "var(--text)", marginBottom: "8px" }}>
              Check your inbox
            </h1>
            <p style={{ fontSize: "14px", color: "var(--text-muted)", lineHeight: "1.5", marginBottom: "12px" }}>
              We have sent a verification link to <strong style={{ color: "var(--text)" }}>{email}</strong>. Please click the link to activate your PitchDock account.
            </p>
            <p style={{ fontSize: "13px", color: "var(--text-dim)", fontStyle: "italic", marginBottom: "24px" }}>
              (If you can't find it, please check your spam or junk folder.)
            </p>
            
            <Link href="/login" className="btn btn-primary btn-block">
              Back to Sign in →
            </Link>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="grid-backdrop"></div>

      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: "40px 20px" }}>
        <div style={{
          width: "100%",
          maxWidth: "420px",
          backgroundColor: "var(--surface)",
          border: "1px solid var(--border-strong)",
          borderRadius: "18px",
          padding: "36px",
          boxShadow: "0 20px 50px rgba(0, 0, 0, 0.6)",
          position: "relative",
          zIndex: 2
        }}>
          <div style={{ textAlign: "center", marginBottom: "28px" }}>
            <img 
              src="/orangelogo.png" 
              alt="PitchDock Logo" 
              style={{ display: "block", margin: "0 auto 16px", width: "52px", height: "52px", borderRadius: "50%", objectFit: "cover", boxShadow: "0 0 20px rgba(255, 90, 46, 0.3)" }} 
            />
            <h1 style={{ fontFamily: "var(--font-display)", fontSize: "28px", fontWeight: 700, color: "var(--text)", marginBottom: "8px" }}>
              Get started free
            </h1>
            <p style={{ fontSize: "14px", color: "var(--text-muted)" }}>
              Create an account and launch your personal AI outreach machine.
            </p>
          </div>

          {error && (
            <div style={{
              backgroundColor: "rgba(255, 90, 46, 0.1)",
              border: "1px solid var(--signal)",
              color: "var(--signal-soft)",
              borderRadius: "8px",
              padding: "12px 16px",
              fontSize: "13.5px",
              marginBottom: "24px",
              lineHeight: "1.4"
            }}>
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "18px" }}>
            <div>
              <label style={{ fontSize: "12px", fontFamily: "var(--font-mono)", color: "var(--text-muted)", display: "block", marginBottom: "6px" }} htmlFor="email">
                Email address
              </label>
              <input
                id="email"
                type="email"
                required
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                style={{
                  width: "100%",
                  padding: "12px 14px",
                  borderRadius: "8px",
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border-strong)",
                  color: "var(--text)",
                  outline: "none",
                  fontSize: "14px"
                }}
              />
            </div>

            <div>
              <label style={{ fontSize: "12px", fontFamily: "var(--font-mono)", color: "var(--text-muted)", display: "block", marginBottom: "6px" }} htmlFor="password">
                Password
              </label>
              <div style={{ position: "relative" }}>
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  required
                  placeholder="At least 6 characters"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  style={{
                    width: "100%",
                    padding: "12px 14px",
                    paddingRight: "60px",
                    borderRadius: "8px",
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--border-strong)",
                    color: "var(--text)",
                    outline: "none",
                    fontSize: "14px"
                  }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  style={{
                    position: "absolute",
                    right: "12px",
                    top: "50%",
                    transform: "translateY(-50%)",
                    border: "none",
                    background: "none",
                    cursor: "pointer",
                    fontSize: "12px",
                    fontWeight: 600,
                    color: "var(--signal-soft)"
                  }}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
            </div>

            <div>
              <label style={{ fontSize: "12px", fontFamily: "var(--font-mono)", color: "var(--text-muted)", display: "block", marginBottom: "6px" }} htmlFor="confirmPassword">
                Confirm Password
              </label>
              <input
                id="confirmPassword"
                type="password"
                required
                placeholder="Repeat password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
                style={{
                  width: "100%",
                  padding: "12px 14px",
                  borderRadius: "8px",
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border-strong)",
                  color: "var(--text)",
                  outline: "none",
                  fontSize: "14px"
                }}
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary btn-block"
              disabled={loading}
              style={{
                padding: "12px",
                fontSize: "14px",
                fontWeight: 600,
                marginTop: "6px",
                justifyContent: "center"
              }}
            >
              {loading ? "Creating account..." : "Sign up for console →"}
            </button>
          </form>

          <div style={{ textAlign: "center", marginTop: "24px", fontSize: "13.5px", color: "var(--text-muted)" }}>
            Already have an account?{" "}
            <Link href="/login" style={{ color: "var(--signal-soft)", fontWeight: 600, textDecoration: "none" }}>
              Sign in
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}
