"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type {
  AuthSession,
  AuthTokens,
  AuthUser,
} from "@/features/auth/types/auth.types";

interface AuthState {
  user: AuthUser | null;
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  rememberMe: boolean;
  login: (session: AuthSession, rememberMe?: boolean) => void;
  logout: () => void;
  setUser: (user: AuthUser) => void;
  setTokens: (tokens: AuthTokens) => void;
  clearAuth: () => void;
}

const AUTH_STORAGE_KEY = "agentvox-auth";

const initialState = {
  user: null,
  accessToken: null,
  refreshToken: null,
  isAuthenticated: false,
  rememberMe: false,
} as const;

const authStorage = {
  getItem: (name: string): string | null => {
    if (typeof window === "undefined") {
      return null;
    }

    return localStorage.getItem(name) ?? sessionStorage.getItem(name);
  },
  setItem: (name: string, value: string): void => {
    if (typeof window === "undefined") {
      return;
    }

    let rememberMe = false;

    try {
      const parsed = JSON.parse(value) as {
        state?: { rememberMe?: boolean };
      };
      rememberMe = Boolean(parsed.state?.rememberMe);
    } catch {
      rememberMe = false;
    }

    if (rememberMe) {
      localStorage.setItem(name, value);
      sessionStorage.removeItem(name);
      return;
    }

    sessionStorage.setItem(name, value);
    localStorage.removeItem(name);
  },
  removeItem: (name: string): void => {
    if (typeof window === "undefined") {
      return;
    }

    localStorage.removeItem(name);
    sessionStorage.removeItem(name);
  },
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      ...initialState,
      login: (session, rememberMe = false) => {
        set({
          user: session.user,
          accessToken: session.accessToken,
          refreshToken: session.refreshToken,
          isAuthenticated: true,
          rememberMe,
        });
      },
      logout: () => {
        set({ ...initialState });
      },
      setUser: (user) => {
        set({
          user,
          isAuthenticated: true,
        });
      },
      setTokens: (tokens) => {
        set({
          accessToken: tokens.accessToken,
          refreshToken: tokens.refreshToken,
          isAuthenticated: Boolean(tokens.accessToken),
        });
      },
      clearAuth: () => {
        set({ ...initialState });
      },
    }),
    {
      name: AUTH_STORAGE_KEY,
      storage: createJSONStorage(() => authStorage),
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        isAuthenticated: state.isAuthenticated,
        rememberMe: state.rememberMe,
      }),
    }
  )
);
