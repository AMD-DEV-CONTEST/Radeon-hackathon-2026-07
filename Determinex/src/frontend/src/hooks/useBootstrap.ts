"use client";
import { useState, useEffect } from "react";
import { invokeSafe, isTauri } from "@/lib/api";

export interface BootstrapState {
  isBootstrapping: boolean;
  bootTier: string | null;
  bootError: string | null;
  bootProgress: number;
  dismissBootError: () => void;
}

export function useBootstrap(): BootstrapState {
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [bootTier, setBootTier] = useState<string | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [bootProgress, setBootProgress] = useState(0);

  useEffect(() => {
    if (!isTauri()) {
      setIsBootstrapping(false);
      return;
    }
    // Stages mirror the sequence in ipc_bootstrap.rs:
    //   0→20%  Docker check   (~500ms)
    //   20→45% Ollama verify  (~1s)
    //   45→65% VRAM probe     (~500ms)
    //   65→88% Model checks   (~5-30s)
    //   88→97% Determinex tags   (~1s)
    const stages: [number, number][] = [
      [20, 500],
      [45, 1500],
      [65, 2500],
      [88, 8000],
      [97, 12000],
    ];
    const timers: ReturnType<typeof setTimeout>[] = [];
    stages.forEach(([pct, delay]) => {
      timers.push(setTimeout(() => setBootProgress(pct), delay));
    });

    let settled = false;
    const finish = (tier: string | null, error: string | null) => {
      if (settled) return;
      settled = true;
      timers.forEach(clearTimeout);
      if (tier) setBootTier(tier);
      if (error) {
        setBootError(error);
        setIsBootstrapping(false);
        return;
      }
      setBootProgress(100);
      setTimeout(() => setIsBootstrapping(false), 300);
    };

    // Hard ceiling on the splash. Two things made this necessary:
    //
    //  1. The bars above are a pure setTimeout animation, not real progress --
    //     they advance whether or not the backend is alive, so a hung boot
    //     looks exactly like a slow one.
    //  2. invokeSafe never throws (it returns null on failure), so the .catch()
    //     this used to rely on was unreachable dead code. Nothing could ever
    //     set bootError, and nothing bounded the wait.
    //
    // Net effect: if initialize_system never resolved, the app sat on the
    // splash forever with no error, no escape, and a progress bar still
    // implying work. Hit live 2026-07-27, stuck at 65%. 90s is well beyond the
    // ~30s worst case the stage table itself documents.
    const BOOT_TIMEOUT_MS = 90_000;
    const timeout = setTimeout(() => {
      finish(
        null,
        "Startup did not finish within 90 seconds. The backend may still be " +
          "probing hardware or pulling models — check the app log. You can " +
          "continue and retry from Settings."
      );
    }, BOOT_TIMEOUT_MS);
    timers.push(timeout);

    invokeSafe<{ tier: string }>("initialize_system")
      .then((result) => {
        // A null result means invokeSafe swallowed a real failure. Treat that
        // as an error instead of silently booting into a half-initialized app.
        if (result === null) {
          finish(null, "Startup could not reach the desktop backend (initialize_system failed).");
          return;
        }
        finish(result.tier, null);
      })
      .catch((err: unknown) => finish(null, String(err)));

    return () => {
      settled = true;
      timers.forEach(clearTimeout);
    };
  }, []);

  return {
    isBootstrapping,
    bootTier,
    bootError,
    bootProgress,
    dismissBootError: () => setIsBootstrapping(false),
  };
}
