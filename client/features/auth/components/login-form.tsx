"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { ArrowRight, Loader2, Mail } from "lucide-react";
import Link from "next/link";
import { useForm } from "react-hook-form";

import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/features/auth/components/password-input";
import { RememberMe } from "@/features/auth/components/remember-me";
import { SocialLogin } from "@/features/auth/components/social-login";
import {
  getLoginErrorMessage,
  getLoginFieldErrors,
  useLogin,
} from "@/features/auth/hooks/use-login";
import {
  loginSchema,
  type LoginFormValues,
} from "@/features/auth/schemas/login.schema";
import { cn } from "@/lib/utils";

export function LoginForm() {
  const loginMutation = useLogin();

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      email: "",
      password: "",
      rememberMe: false,
    },
    mode: "onSubmit",
  });

  const rememberMe = watch("rememberMe");
  const isLoading = isSubmitting || loginMutation.isPending;
  const serverError = loginMutation.error
    ? getLoginErrorMessage(loginMutation.error)
    : null;

  const onSubmit = handleSubmit(async (values) => {
    if (isLoading) {
      return;
    }

    try {
      await loginMutation.mutateAsync(values);
    } catch (error) {
      const fieldErrors = getLoginFieldErrors(error);

      for (const [field, message] of Object.entries(fieldErrors)) {
        if (field === "email" || field === "password" || field === "rememberMe") {
          setError(field, { type: "server", message });
        }
      }
    }
  });

  return (
    <motion.div
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: "easeOut" }}
      className="mx-auto w-full max-w-md"
    >
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
          Welcome Back
        </h1>
        <p className="mt-2 text-sm text-muted-foreground sm:text-base">
          Enter your credentials to access your command center.
        </p>
      </div>

      <SocialLogin disabled={isLoading} />

      <div
        className="my-6 flex items-center gap-3"
        role="separator"
        aria-label="Or continue with email"
      >
        <div className="h-px flex-1 bg-border" />
        <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          Or continue with
        </span>
        <div className="h-px flex-1 bg-border" />
      </div>

      <form className="space-y-5" onSubmit={onSubmit} noValidate>
        <div className="space-y-2">
          <Label htmlFor="email">Work Email</Label>
          <div className="relative">
            <Mail
              className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="name@company.com"
              disabled={isLoading}
              aria-invalid={Boolean(errors.email) || undefined}
              aria-describedby={errors.email ? "email-error" : undefined}
              className="pl-10"
              {...register("email")}
            />
          </div>
          {errors.email ? (
            <p id="email-error" role="alert" className="text-xs text-destructive">
              {errors.email.message}
            </p>
          ) : null}
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor="password">Password</Label>
            <Link
              href="/forgot-password"
              className="text-xs font-medium text-primary transition-colors hover:text-primary/80"
            >
              Forgot password?
            </Link>
          </div>
          <PasswordInput
            id="password"
            placeholder="••••••••"
            disabled={isLoading}
            error={Boolean(errors.password)}
            aria-describedby={errors.password ? "password-error" : undefined}
            {...register("password")}
          />
          {errors.password ? (
            <p
              id="password-error"
              role="alert"
              className="text-xs text-destructive"
            >
              {errors.password.message}
            </p>
          ) : null}
        </div>

        <RememberMe
          checked={rememberMe}
          disabled={isLoading}
          onCheckedChange={(checked) => {
            setValue("rememberMe", checked, {
              shouldDirty: true,
              shouldValidate: true,
            });
          }}
        />

        {serverError ? (
          <div
            role="alert"
            className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {serverError}
          </div>
        ) : null}

        <motion.div
          whileHover={{ scale: isLoading ? 1 : 1.01 }}
          whileTap={{ scale: isLoading ? 1 : 0.99 }}
        >
          <Button
            type="submit"
            disabled={isLoading}
            className="h-11 w-full glow-purple"
            aria-busy={isLoading}
          >
            {isLoading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Signing in...
              </>
            ) : (
              <>
                Sign In to Dashboard
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </>
            )}
          </Button>
        </motion.div>
      </form>

      <p className="mt-6 text-center text-sm text-muted-foreground">
        Don&apos;t have an account?{" "}
        <Link
          href="/register"
          className={cn(
            buttonVariants({ variant: "link" }),
            "h-auto p-0 text-sm font-semibold text-primary"
          )}
        >
          Create one now
        </Link>
      </p>

      <div className="mt-10 border-t border-border pt-6">
        <p className="text-center text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Trusted by leading engineering teams
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-x-6 gap-y-2">
          {["Notion", "Linear", "Vercel", "Stripe"].map((brand) => (
            <span
              key={brand}
              className="text-sm font-semibold tracking-wide text-white/35"
            >
              {brand}
            </span>
          ))}
        </div>
      </div>
    </motion.div>
  );
}
