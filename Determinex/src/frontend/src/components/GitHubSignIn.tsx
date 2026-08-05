"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
// lucide-react removed its brand icons (there is no `Github` export in this
// version -- importing it yields undefined and React throws "Element type is
// invalid" at render). Generic icons instead; the labels say GitHub.
import { LogIn, CircleUserRound, Copy, Check, ExternalLink, LogOut, Loader2 } from "lucide-react";

/**
 * Real GitHub sign-in, replacing "paste a personal access token".
 *
 * Device Authorization Grant (RFC 8628): we show a short code, the user types
 * it on github.com, and we poll until they finish. No client secret is needed,
 * which matters because a desktop app cannot keep one -- shipping a secret in
 * the binary is publishing it.
 *
 * The access token never reaches this component. `github_device_poll` stores it
 * server-side in the same row a pasted token uses and returns only a status, so
 * the token never sits in JS memory or shows up in a devtools network pane.
 *
 * Raw `invoke`, not invokeSafe -- see Issue 1 in
 * docs/audits/IDE_SHELL_AUDIT_20260727.md. A failed sign-in must be
 * distinguishable from a pending one, and invokeSafe collapses both to null.
 */

type Start = {
  userCode: string;
  verificationUri: string;
  deviceCode: string;
  interval: number;
  expiresIn: number;
};

type Poll = { status: string; interval?: number | null; message?: string | null };

interface Props {
  /** True when a GITHUB_TOKEN row already exists. */
  connected?: boolean;
  onChange?: () => void;
}

export function GitHubSignIn({ connected = false, onChange }: Props) {
  const [start, setStart] = useState<Start | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stop = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }, []);
  useEffect(() => stop, [stop]);

  const poll = useCallback(
    (deviceCode: string, intervalSec: number, deadline: number) => {
      timer.current = setTimeout(async () => {
        if (Date.now() > deadline) {
          setError("The code expired before it was approved. Start again.");
          setStart(null);
          return;
        }
        try {
          const res = await invoke<Poll>("github_device_poll", { deviceCode });
          if (res.status === "authorized") {
            setDone(true);
            setStart(null);
            onChange?.();
            return;
          }
          if (res.status === "pending" || res.status === "slow_down") {
            // RFC 8628: on slow_down the server may hand back a longer interval,
            // and polling faster than told can get the request rejected outright.
            poll(
              deviceCode,
              res.interval ?? intervalSec + (res.status === "slow_down" ? 5 : 0),
              deadline
            );
            return;
          }
          setError(res.message ?? "Sign-in was not completed.");
          setStart(null);
        } catch (e) {
          setError(e instanceof Error ? e.message : String(e));
          setStart(null);
        }
      }, intervalSec * 1000);
    },
    [onChange]
  );

  const begin = async () => {
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const s = await invoke<Start>("github_device_start");
      setStart(s);
      poll(s.deviceCode, s.interval, Date.now() + s.expiresIn * 1000);
      // Best-effort: if the browser will not open, the code and link are still
      // on screen, so this failing is not worth surfacing as an error.
      invoke("github_open_verification", { url: s.verificationUri }).catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    setBusy(true);
    setError(null);
    try {
      await invoke("github_sign_out");
      setDone(false);
      onChange?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!start) return;
    try {
      await navigator.clipboard.writeText(start.userCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked -- the code is visible on screen regardless */
    }
  };

  if (connected || done) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-emerald-500/25 bg-emerald-950/20 px-3 py-2">
        <CircleUserRound size={13} className="shrink-0 text-emerald-400" />
        <span className="flex-1 text-label font-bold text-emerald-300">GitHub connected</span>
        <button
          onClick={signOut}
          disabled={busy}
          data-testid="github-sign-out"
          className="flex items-center gap-1 text-eyebrow font-bold uppercase tracking-widest text-gray-500 transition-colors hover:text-red-300 disabled:opacity-40"
        >
          <LogOut size={10} /> Sign out
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {!start && (
        <button
          onClick={begin}
          disabled={busy}
          data-testid="github-sign-in"
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-white/15 bg-white/[0.04] px-3 py-2 text-label font-bold text-white/85 transition-colors hover:bg-white/[0.08] disabled:opacity-40"
        >
          {busy ? <Loader2 size={12} className="animate-spin" /> : <LogIn size={13} />}
          Sign in with GitHub
        </button>
      )}

      {start && (
        <div className="space-y-2 rounded-lg border border-white/10 bg-black/40 p-3">
          <p className="text-label leading-relaxed text-gray-400">
            Enter this code on GitHub to finish signing in:
          </p>
          <div className="flex items-center gap-2">
            <code
              data-testid="github-user-code"
              className="flex-1 rounded-md border border-[var(--determinex-accent)]/30 bg-black/60 px-3 py-2 text-center font-mono text-title font-black tracking-[0.25em] text-[var(--determinex-accent)]"
            >
              {start.userCode}
            </code>
            <button
              onClick={copy}
              title="Copy code"
              className="shrink-0 rounded-md border border-white/10 p-2 text-gray-400 transition-colors hover:text-white"
            >
              {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
            </button>
          </div>
          <a
            href={start.verificationUri}
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-center gap-1.5 text-label text-gray-500 transition-colors hover:text-[var(--determinex-accent)]"
          >
            <ExternalLink size={10} /> {start.verificationUri}
          </a>
          <p className="flex items-center justify-center gap-1.5 font-mono text-meta text-gray-600">
            <Loader2 size={9} className="animate-spin" /> waiting for approval…
          </p>
        </div>
      )}

      {error && (
        <p className="rounded-md border border-red-500/25 bg-red-950/20 px-2.5 py-1.5 font-mono text-label leading-relaxed text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
