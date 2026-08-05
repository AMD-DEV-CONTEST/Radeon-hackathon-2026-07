"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Navbar() {
  const pathname = usePathname();

  return (
    <header>
      <nav className="nav">
        <Link href="/" className="logo" style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <img 
            src="/orangelogo.png" 
            alt="PitchDock Logo" 
            style={{ height: "28px", width: "28px", objectFit: "cover", borderRadius: "50%" }} 
          />
          <span>Pitch<span style={{ color: "var(--signal)" }}>Dock</span></span>
        </Link>
        <div className="nav-links">
          <Link href="/#features">Features</Link>
          <Link href="/#pricing">Pricing</Link>
          <Link href="/#faq">FAQ</Link>
          <Link href="/privacy">Privacy</Link>
        </div>
        <div className="nav-actions">
          {pathname !== "/login" && pathname !== "/signup" && (
            <Link href="/login" className="signin">Sign in</Link>
          )}

          {pathname === "/login" || pathname === "/signup" ? (
            <Link 
              href={pathname === "/login" ? "/signup" : "/login"} 
              className="btn btn-ghost btn-sm"
            >
              {pathname === "/login" ? "Sign up" : "Sign in"}
            </Link>
          ) : (
            <Link href="/dashboard" className="btn btn-primary btn-sm">
              Launch console
            </Link>
          )}
        </div>
      </nav>
    </header>
  );
}
