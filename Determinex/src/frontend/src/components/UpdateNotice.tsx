"use client";

/**
 * UpdateNotice — in-app update check.
 *
 * WHY THIS EXISTS
 * ---------------
 * Until 2026-07-29 there was no update path of any kind. Pushing a fix to git rebuilt the
 * download artifacts but never touched an installed app, so every user stayed on the version
 * they first installed until they manually downloaded and re-ran the installer. Worse, that
 * property is one-way: a build shipped WITHOUT the updater can never learn to update itself,
 * so the first published cohort would have been on manual reinstalls permanently. That is why
 * this is in the first public build rather than a later one.
 *
 * Deliberately quiet. It checks once, a few seconds after mount so it never competes with
 * first-run setup, and it stays silent unless an update actually exists. Any failure is
 * swallowed to a console warning: an offline user, a GitHub outage, or a release with no
 * `latest.json` yet must never produce an error dialog on top of a working app.
 *
 * Downloading is explicit. Nothing installs until the user asks, because installing relaunches
 * the app and losing someone's in-progress session to a background update would be worse than
 * shipping the fix a day later.
 *
 * IT ALSO RESPECTS THE OFFLINE NETWORK POLICY (fixed 2026-07-30)
 * -------------------------------------------------------------
 * The check used to fire unconditionally, so an install set to `offline` still made an outbound
 * HTTPS request to github.com on every launch. This app ships an explicit three-state network
 * policy and `AiRouterContext` already refuses to route a cloud model under `offline` — so the
 * updater was contradicting a guarantee the rest of the product keeps, in a product whose whole
 * position is local-first. "It's only a version string" is not the point: the user asked for no
 * network, and something went to the network.
 *
 * `cloaked` still checks, deliberately. Cloaked means cloud calls are allowed with identifiers
 * obfuscated; an update check carries no repository identifiers at all, so suppressing it there
 * would cost every cloaked user their security fixes for no privacy gain.
 */

import { useCallback, useEffect, useState } from "react";

import { useSettings } from "@/contexts/SettingsContext";

type Phase = "idle" | "available" | "downloading" | "ready" | "failed";

// The check runs after this delay so a fresh install's SetupWizard owns the screen first.
const CHECK_DELAY_MS = 6_000;

export function UpdateNotice() {
  const { networkPolicy } = useSettings();
  const offline = networkPolicy === "offline";
  const [phase, setPhase] = useState<Phase>("idle");
  const [version, setVersion] = useState("");
  const [notes, setNotes] = useState("");
  const [progress, setProgress] = useState(0);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    // The user asked for no network. Do not schedule the timer at all -- returning early from
    // inside the callback would still have armed it, and a policy change mid-timer would then
    // fire a request the current policy forbids.
    if (offline) return;

    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        // Imported lazily: in a browser dev context (`next dev` without Tauri) there is no
        // updater at all, and a top-level import would break the page rather than the feature.
        const { check } = await import("@tauri-apps/plugin-updater");
        const update = await check();
        if (cancelled || !update) return;
        setVersion(update.version);
        setNotes(update.body ?? "");
        setPhase("available");
      } catch (err) {
        // Not a user-facing condition. No endpoint, no network, or not running under Tauri.
        console.warn("[UpdateNotice] update check skipped:", err);
      }
    }, CHECK_DELAY_MS);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // `offline` is a dependency: switching to offline must cancel a pending check, and switching
    // away from it must arm one without needing a restart.
  }, [offline]);

  const install = useCallback(async () => {
    setPhase("downloading");
    setProgress(0);
    try {
      const { check } = await import("@tauri-apps/plugin-updater");
      const update = await check();
      if (!update) {
        setPhase("idle");
        return;
      }

      let total = 0;
      let received = 0;
      await update.downloadAndInstall((event) => {
        if (event.event === "Started") {
          total = event.data.contentLength ?? 0;
        } else if (event.event === "Progress") {
          received += event.data.chunkLength ?? 0;
          // A missing content-length is normal; show indeterminate rather than a fake number.
          if (total > 0) setProgress(Math.min(100, Math.round((received / total) * 100)));
        } else if (event.event === "Finished") {
          setProgress(100);
        }
      });

      setPhase("ready");
      const { relaunch } = await import("@tauri-apps/plugin-process");
      await relaunch();
    } catch (err) {
      console.error("[UpdateNotice] update failed:", err);
      setPhase("failed");
    }
  }, []);

  // Also hidden when offline, not just unscheduled. If the policy flips to offline while a notice
  // is already on screen, its Install button would still call check() and downloadAndInstall().
  if (offline || dismissed || phase === "idle") return null;

  return (
    <div className="fixed bottom-5 right-5 z-[60] w-[22rem] rounded-xl border border-white/15 bg-white/10 p-4 font-sans text-slate-100 shadow-[0_25px_50px_-12px_rgba(0,0,0,0.5)] backdrop-blur-xl">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold tracking-tight">
            {phase === "failed" ? "Update failed" : `Determinex ${version} is available`}
          </p>
          {phase === "available" && notes ? (
            <p className="mt-1 line-clamp-3 text-xs text-slate-300">{notes}</p>
          ) : null}
          {phase === "downloading" ? (
            <p className="mt-1 text-xs text-slate-300">
              {progress > 0 ? `Downloading — ${progress}%` : "Downloading…"}
            </p>
          ) : null}
          {phase === "ready" ? (
            <p className="mt-1 text-xs text-slate-300">Installed. Restarting…</p>
          ) : null}
          {phase === "failed" ? (
            <p className="mt-1 text-xs text-slate-300">
              You can keep working. Download the latest installer when convenient.
            </p>
          ) : null}
        </div>
        <button
          type="button"
          aria-label="Dismiss update notice"
          onClick={() => setDismissed(true)}
          className="shrink-0 rounded-md px-2 py-1 text-slate-400 transition-colors hover:bg-white/10 hover:text-slate-100"
        >
          ✕
        </button>
      </div>

      {phase === "downloading" ? (
        <div className="mt-3 h-1 w-full overflow-hidden rounded-full bg-white/10">
          <div
            className="h-full rounded-full bg-indigo-400 transition-[width] duration-300"
            style={{ width: progress > 0 ? `${progress}%` : "35%" }}
          />
        </div>
      ) : null}

      {phase === "available" ? (
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={install}
            className="rounded-lg bg-indigo-500 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-indigo-400"
          >
            Update and restart
          </button>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="rounded-lg border border-white/15 px-3 py-1.5 text-xs font-medium text-slate-200 transition-colors hover:bg-white/10"
          >
            Later
          </button>
        </div>
      ) : null}
    </div>
  );
}
