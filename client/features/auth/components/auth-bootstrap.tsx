"use client";

import { useEffect, useState, type ReactNode } from "react";

import { useCurrentUser } from "@/features/auth/hooks/use-current-user";
import { useAuthStore } from "@/features/auth/store/auth.store";

interface AuthBootstrapProps {
  children: ReactNode;
}

/**
 * Restores the authenticated user after Zustand persist hydration.
 * Safe to mount under the shared QueryProvider.
 */
export function AuthBootstrap({ children }: AuthBootstrapProps) {
  const [hasHydrated, setHasHydrated] = useState(() =>
    useAuthStore.persist.hasHydrated()
  );

  useEffect(() => {
    const unsubFinish = useAuthStore.persist.onFinishHydration(() => {
      setHasHydrated(true);
    });

    if (useAuthStore.persist.hasHydrated()) {
      setHasHydrated(true);
    }

    return unsubFinish;
  }, []);

  useCurrentUser({ enabled: hasHydrated });

  return children;
}
