"use client";

import { createClient, type Session, type SupabaseClient, type User } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
const dashboardTenantId = process.env.NEXT_PUBLIC_DASHBOARD_TENANT_ID || "default";

// Only public Supabase settings are ever bundled into the browser client.
const browserAuth: SupabaseClient | null = supabaseUrl && supabaseAnonKey
  ? createClient(supabaseUrl, supabaseAnonKey, { auth: { persistSession: true, autoRefreshToken: true } })
  : null;

let currentSession: Session | null = null;
let dashboardApiKey: string | null = null;

export function isBrowserAuthConfigured(): boolean {
  return browserAuth !== null;
}

export async function loadBrowserSession(): Promise<{ user: User | null; session: Session | null }> {
  if (!browserAuth) return { user: null, session: null };
  const { data } = await browserAuth.auth.getSession();
  currentSession = data.session;
  return { user: data.session?.user || null, session: data.session };
}

export function subscribeToBrowserAuth(onChange: (session: Session | null) => void): (() => void) | null {
  if (!browserAuth) return null;
  const { data } = browserAuth.auth.onAuthStateChange((_event, session) => {
    currentSession = session;
    onChange(session);
  });
  return () => data.subscription.unsubscribe();
}

export async function signInWithPassword(email: string, password: string): Promise<{ error: string | null }> {
  if (!browserAuth) return { error: "Supabase Auth 未配置" };
  const { data, error } = await browserAuth.auth.signInWithPassword({ email, password });
  currentSession = data.session;
  return { error: error?.message || null };
}

export async function signUpWithPassword(email: string, password: string, name: string): Promise<{ error: string | null; user: User | null }> {
  if (!browserAuth) return { error: "Supabase Auth 未配置", user: null };
  const { data, error } = await browserAuth.auth.signUp({ email, password, options: { data: { name } } });
  if (error) return { error: error.message, user: null };
  currentSession = data.session;
  return { error: null, user: data.user };
}

export async function signOutBrowser(): Promise<void> {
  dashboardApiKey = null;
  currentSession = null;
  if (browserAuth) await browserAuth.auth.signOut();
}

export function setDashboardApiKey(key: string | null): void {
  dashboardApiKey = key?.trim() || null;
}

export async function getDashboardAuthHeaders(): Promise<Headers> {
  const headers = new Headers();
  if (dashboardApiKey) {
    headers.set("x-api-key", dashboardApiKey);
    headers.set("x-tenant-id", dashboardTenantId);
    return headers;
  }
  if (!currentSession && browserAuth) await loadBrowserSession();
  if (currentSession?.access_token) headers.set("Authorization", `Bearer ${currentSession.access_token}`);
  return headers;
}
