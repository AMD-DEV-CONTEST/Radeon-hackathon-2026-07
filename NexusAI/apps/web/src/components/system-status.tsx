"use client";

import { useEffect, useState } from "react";
import { getHealth } from "@/lib/api";

export function SystemStatus() {
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    getHealth()
      .then(() => setOnline(true))
      .catch(() => setOnline(false));
  }, []);

  const label =
    online === null
      ? "CONNECTING"
      : online
        ? "NEXUS CORE ONLINE"
        : "NEXUS CORE OFFLINE";

  return (
    <div className="inline-flex items-center gap-3 rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-xs tracking-[0.22em] text-white/70 backdrop-blur">
      <span
        className={`h-2 w-2 rounded-full ${
          online === null
            ? "bg-yellow-300"
            : online
              ? "bg-emerald-300 shadow-[0_0_16px_rgba(110,231,183,0.8)]"
              : "bg-red-400"
        }`}
      />
      {label}
    </div>
  );
}
