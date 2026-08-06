"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

export function TopBar() {
  const [tokensPerSecond, setTokensPerSecond] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const { current_tokens_per_second } = await api.liveMetrics();
        if (!cancelled) setTokensPerSecond(current_tokens_per_second);
      } catch {
        if (!cancelled) setTokensPerSecond(null);
      }
    }

    poll();
    const interval = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="topbar">
      <Link href="/" className="wordmark">
        AEG<span>I</span>S
      </Link>
      <nav style={{ display: "flex", alignItems: "center", gap: 24 }}>
        <Link href="/benchmarks" className="live-stat" style={{ cursor: "pointer" }}>
          GPU benchmarks
        </Link>
        <div className="live-stat">
          <span className="pulse-dot" />
          {tokensPerSecond !== null ? `${tokensPerSecond.toFixed(1)} tok/s` : "inference idle"}
        </div>
      </nav>
    </div>
  );
}
