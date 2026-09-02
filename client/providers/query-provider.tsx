"use client";

import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { AuthBootstrap } from "@/features/auth/components/auth-bootstrap";

interface QueryProviderProps {
  children: ReactNode;
}

export function QueryProvider({ children }: QueryProviderProps) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
          mutations: {
            retry: false,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthBootstrap>{children}</AuthBootstrap>
    </QueryClientProvider>
  );
}
