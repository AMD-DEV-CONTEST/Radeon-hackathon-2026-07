"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Navbar from "@/components/Navbar";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("authToken");
    if (token) {
      router.push("/dashboard");
    }
  }, [router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
        credentials: "include"
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Invalid email or password");
      }

      localStorage.setItem("authToken", data.token);
      localStorage.setItem("authUser", JSON.stringify(data.user));
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

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
              Welcome back
            </h1>
            <p style={{ fontSize: "14px", color: "var(--text-muted)" }}>
              Sign in to manage your automated cold outreach campaigns.
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

          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
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
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                <label style={{ fontSize: "12px", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }} htmlFor="password">
                  Password
                </label>
              </div>
              <div style={{ position: "relative" }}>
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  required
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
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
              {loading ? "Signing in..." : "Sign in to console →"}
            </button>
          </form>

          <div style={{ textAlign: "center", marginTop: "24px", fontSize: "13.5px", color: "var(--text-muted)" }}>
            Don't have an account?{" "}
            <Link href="/signup" style={{ color: "var(--signal-soft)", fontWeight: 600, textDecoration: "none" }}>
              Sign up free
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}
