"use client";

import { createContext, FormEvent, useContext, useEffect, useState } from "react";
import {
  getDashboardAuthHeaders,
  isBrowserAuthConfigured,
  loadBrowserSession,
  setDashboardApiKey,
  signInWithPassword,
  signUpWithPassword,
  signOutBrowser,
  subscribeToBrowserAuth,
} from "@/lib/browser-api";
import { ALL_ROLES, getRoleLabel, type Role } from "@/lib/rbac";
import { ShieldCheck, LogOut, KeyRound, Mail, UserPlus } from "lucide-react";
import ThemeToggle from "@/components/dashboard/ThemeToggle";

interface AuthMeResponse {
  role?: Role;
}

export const DashboardAuthContext = createContext<{ role: Role }>({ role: "operator" });

export function useDashboardAuth() {
  return useContext(DashboardAuthContext);
}

export default function DashboardAuthGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [role, setRole] = useState<Role>("operator");
  const [mode, setMode] = useState<"api-key" | "password" | "signup">("password");
  const [apiKey, setApiKey] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const verifyCurrentAuth = async () => {
    const headers = await getDashboardAuthHeaders();
    if (!headers.has("Authorization") && !headers.has("x-api-key")) {
      setAuthenticated(false);
      return;
    }
    const response = await fetch("/api/qa/auth/me", { headers });
    if (!response.ok) {
      setDashboardApiKey(null);
      setAuthenticated(false);
      setError("登录验证失败，请重试");
      return;
    }
    const body = await response.json() as AuthMeResponse;
    setRole(body.role && ALL_ROLES.includes(body.role) ? body.role : "operator");
    setAuthenticated(true);
    setError(null);
  };

  useEffect(() => {
    let active = true;

    // In iframe (e.g. Canvas preview): skip auth for preview
    if (typeof window !== "undefined" && window.self !== window.top) {
      queueMicrotask(() => {
        setReady(true);
        setAuthenticated(true);
      });
      return;
    }

    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const requestUrl = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
      if (!requestUrl.startsWith("/api/qa/") && !requestUrl.startsWith("/api/admin/")) {
        return originalFetch(input, init);
      }
      const headers = new Headers(input instanceof Request ? input.headers : undefined);
      new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
      const authHeaders = await getDashboardAuthHeaders();
      authHeaders.forEach((value, key) => {
        if (!headers.has(key)) headers.set(key, value);
      });
      return originalFetch(input, { ...init, headers });
    };

    // Race auth check against a hard timeout so UI never hangs
    console.log("[AuthGate] starting auth check...");
    const authFlow = loadBrowserSession().then(() => verifyCurrentAuth());
    const hardTimeout = new Promise<void>((resolve) => setTimeout(resolve, 2000));
    Promise.race([authFlow, hardTimeout])
      .catch(() => { if (active) setAuthenticated(false); })
      .finally(() => { console.log("[AuthGate] auth resolved, setting ready=true"); if (active) setReady(true); });

    const unsubscribe = subscribeToBrowserAuth(() => { void verifyCurrentAuth(); });
    return () => { active = false; unsubscribe?.(); window.fetch = originalFetch; };
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      if (mode === "api-key") {
        if (!apiKey.trim()) throw new Error("请输入 API key");
        setDashboardApiKey(apiKey);
        const headers = await getDashboardAuthHeaders();
        const response = await fetch("/api/qa/auth/me", { headers });
        if (!response.ok) {
          setDashboardApiKey(null);
          throw new Error(response.status === 403 ? "该 key 仅可读，当前操作需要 operator" : "API key 无效");
        }
        const body = await response.json() as AuthMeResponse;
        setRole(body.role && ALL_ROLES.includes(body.role) ? body.role : "operator");
        setAuthenticated(true);
      } else if (mode === "signup") {
        if (!name.trim()) throw new Error("请输入姓名");
        if (!email.trim()) throw new Error("请输入邮箱");
        if (!password || password.length < 6) throw new Error("密码至少 6 位");
        const result = await signUpWithPassword(email.trim(), password, name.trim());
        if (result.error) throw new Error(result.error);
        if (result.user) {
          // 调用后端创建 profile 和角色
          await fetch("/api/auth/signup", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ userId: result.user.id, name: name.trim() }),
          });
          // 注册成功后自动登录
          const loginResult = await signInWithPassword(email.trim(), password);
          if (loginResult.error) throw new Error(loginResult.error);
          await verifyCurrentAuth();
        }
      } else {
        const result = await signInWithPassword(email.trim(), password);
        if (result.error) throw new Error(result.error);
        await verifyCurrentAuth();
      }
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "认证失败");
    } finally {
      setSubmitting(false);
    }
  };

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <div className="w-4 h-4 border-2 border-primary/30 border-t-primary rounded-full animate-spin" />
          正在检查登录状态...
        </div>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background px-4">
        <form
          onSubmit={submit}
          className="w-full max-w-sm rounded-2xl border border-border/60 bg-card p-8 shadow-lg shadow-primary/[0.03]"
        >
          {/* Brand — 极简，与侧栏一致 */}
          <div className="flex items-center gap-2.5 mb-6">
            <ShieldCheck className="w-5 h-5 text-[#35C6D3]" strokeWidth={1.75} />
            <h1 className="text-[15px] font-semibold tracking-tight text-foreground">E‑Sentinel</h1>
          </div>

          {/* Mode tabs */}
          <div className="flex border-b border-border text-[13px] font-medium">
            <button
              type="button"
              onClick={() => setMode("api-key")}
              className={`flex items-center gap-1.5 border-b-2 px-3 pb-2.5 transition-colors ${
                mode === "api-key"
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <KeyRound className="w-3.5 h-3.5" />
              API Key
            </button>
            {isBrowserAuthConfigured() && (
              <>
                <button
                  type="button"
                  onClick={() => setMode("password")}
                  className={`flex items-center gap-1.5 border-b-2 px-3 pb-2.5 transition-colors ${
                    mode === "password"
                      ? "border-primary text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Mail className="w-3.5 h-3.5" />
                  登录
                </button>
                <button
                  type="button"
                  onClick={() => setMode("signup")}
                  className={`flex items-center gap-1.5 border-b-2 px-3 pb-2.5 transition-colors ${
                    mode === "signup"
                      ? "border-primary text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <UserPlus className="w-3.5 h-3.5" />
                  注册
                </button>
              </>
            )}
          </div>

          {/* Inputs */}
          {mode === "api-key" ? (
            <label className="mt-5 block text-[13px] font-medium text-foreground">
              API Key
              <input
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                type="password"
                autoComplete="off"
                className="mt-1.5 w-full rounded-lg border border-input bg-background px-3.5 py-2.5 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 transition-all placeholder:text-muted-foreground/50"
                placeholder="ADMIN_VIEWER_KEY 或 ADMIN_API_KEY"
              />
            </label>
          ) : mode === "signup" ? (
            <div className="mt-5 space-y-3">
              <label className="block text-[13px] font-medium text-foreground">
                姓名
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  type="text"
                  autoComplete="name"
                  className="mt-1.5 w-full rounded-lg border border-input bg-background px-3.5 py-2.5 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 transition-all"
                  placeholder="你的名字"
                />
              </label>
              <label className="block text-[13px] font-medium text-foreground">
                邮箱
                <input
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  type="email"
                  autoComplete="username"
                  className="mt-1.5 w-full rounded-lg border border-input bg-background px-3.5 py-2.5 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 transition-all"
                />
              </label>
              <label className="block text-[13px] font-medium text-foreground">
                密码
                <input
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  type="password"
                  autoComplete="new-password"
                  className="mt-1.5 w-full rounded-lg border border-input bg-background px-3.5 py-2.5 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 transition-all"
                  placeholder="至少 6 位"
                />
              </label>
            </div>
          ) : (
            <div className="mt-5 space-y-3">
              <label className="block text-[13px] font-medium text-foreground">
                邮箱
                <input
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  type="email"
                  autoComplete="username"
                  className="mt-1.5 w-full rounded-lg border border-input bg-background px-3.5 py-2.5 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 transition-all"
                />
              </label>
              <label className="block text-[13px] font-medium text-foreground">
                密码
                <input
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  type="password"
                  autoComplete="current-password"
                  className="mt-1.5 w-full rounded-lg border border-input bg-background px-3.5 py-2.5 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 transition-all"
                />
              </label>
            </div>
          )}

          {error && (
            <p className="mt-3 text-[13px] text-destructive font-medium">{error}</p>
          )}

          <button
            disabled={submitting}
            type="submit"
            className="mt-6 w-full rounded-lg bg-primary px-3 py-2.5 text-[13px] font-semibold text-primary-foreground disabled:opacity-40 hover:brightness-110 active:scale-[0.98] transition-all"
          >
            {submitting ? "处理中..." : mode === "signup" ? "注册" : "登录"}
          </button>
        </form>
      </main>
    );
  }

  return (
    <DashboardAuthContext.Provider value={{ role }}>
      <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex justify-end items-center border-b border-border/60 bg-card/80 backdrop-blur-sm px-4 py-2 text-xs text-muted-foreground">
        <span className="mr-3 font-medium">
          {getRoleLabel(role)}已登录
        </span>
        <ThemeToggle className="mr-2" />
        <button
          type="button"
          onClick={() => void signOutBrowser().then(() => setAuthenticated(false))}
          className="flex items-center gap-1 text-foreground/70 hover:text-foreground transition-colors font-medium"
        >
          <LogOut className="w-3 h-3" />
          退出
        </button>
      </div>
        {children}
      </div>
    </DashboardAuthContext.Provider>
  );
}
