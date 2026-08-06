'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';

/**
 * Invisible client component that refreshes dashboard data when:
 * 1. A custom `solo:data-changed` event is dispatched (e.g. from chat after a tool call)
 * 2. Every 60 seconds as a polling fallback
 * 
 * Uses `router.refresh()` which re-runs server components without full page reload.
 * Also clears the server-side cache via API call.
 * 
 * NOTE: Focus-based refresh has been removed because it caused click unresponsiveness —
 * router.refresh() on focus would re-render server components and interrupt user interactions.
 * 
 * User interaction guard: when the user is actively clicking or navigating, refresh is
 * deferred to avoid interrupting the interaction (which caused "need 2-3 clicks to navigate").
 */
export default function DashboardRefresher() {
  const router = useRouter();
  const lastRefresh = useRef(Date.now());
  const mountedRef = useRef(true);
  const interactingRef = useRef(false);

  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  // Track user interaction: set flag on mousedown, clear after a short window
  useEffect(() => {
    const onInteraction = () => {
      interactingRef.current = true;
      // Clear the flag after 800ms (allows any pending navigation to complete)
      setTimeout(() => { interactingRef.current = false; }, 800);
    };
    document.addEventListener('mousedown', onInteraction, { passive: true });
    document.addEventListener('touchstart', onInteraction, { passive: true });
    return () => {
      document.removeEventListener('mousedown', onInteraction);
      document.removeEventListener('touchstart', onInteraction);
    };
  }, []);

  useEffect(() => {
    const refresh = async (forceCacheClear: boolean = false) => {
      if (!mountedRef.current) return;
      const now = Date.now();
      // Throttle: at most once every 5 seconds
      if (now - lastRefresh.current > 5000) {
        // Defer refresh if user is actively interacting
        if (interactingRef.current) {
          setTimeout(() => { if (mountedRef.current && !interactingRef.current) doRefresh(forceCacheClear); }, 1000);
          return;
        }
        await doRefresh(forceCacheClear);
      }
    };

    const doRefresh = async (forceCacheClear: boolean) => {
      if (!mountedRef.current) return;
      lastRefresh.current = Date.now();
      
      // Clear cache via API if needed
      if (forceCacheClear) {
        try {
          await fetch('/api/dashboard?force=1', { method: 'GET' });
        } catch {
          // Ignore cache clear errors
        }
      }
      
      router.refresh();
    };

    // Refresh on custom data-changed event (dispatched from chat)
    // Clear cache since data changed
    const onDataChanged = () => refresh(true);
    window.addEventListener('solo:data-changed', onDataChanged);

    // Polling fallback: every 60 seconds (use cache if fresh)
    const interval = setInterval(() => refresh(false), 60_000);

    return () => {
      window.removeEventListener('solo:data-changed', onDataChanged);
      clearInterval(interval);
    };
  }, [router]);

  return null;
}