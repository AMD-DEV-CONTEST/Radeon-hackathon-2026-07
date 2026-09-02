"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import { ArrowRight, Loader2, Mail, UserRound } from "lucide-react";
import Link from "next/link";
import { Controller, useForm } from "react-hook-form";

import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/features/auth/components/password-input";
import { PasswordStrength } from "@/features/auth/components/password-strength";
import { SocialLogin } from "@/features/auth/components/social-login";
import {
  getRegisterErrorMessage,
  getRegisterFieldErrors,
  useRegister,
} from "@/features/auth/hooks/use-register";
import {
  registerSchema,
  type RegisterFormValues,
} from "@/features/auth/schemas/register.schema";
import { cn } from "@/lib/utils";

export function RegisterForm() {
  const registerMutation = useRegister();

  const {
    register,
    handleSubmit,
    control,
    watch,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      fullName: "",
      email: "",
      password: "",
      confirmPassword: "",
      acceptTerms: false,
      receiveUpdates: true,
    },
    mode: "onSubmit",
  });

  const password = watch("password");
  const isLoading = isSubmitting || registerMutation.isPending;
  const serverError = registerMutation.error
    ? getRegisterErrorMessage(registerMutation.error)
    : null;

  const onSubmit = handleSubmit(async (values) => {
    if (isLoading) {
      return;
    }

    try {
      await registerMutation.mutateAsync(values);
    } catch (error) {
      const fieldErrors = getRegisterFieldErrors(error);
      const fields = [
        "fullName",
        "email",
        "password",
        "confirmPassword",
        "acceptTerms",
        "receiveUpdates",
      ] as const;

      for (const field of fields) {
        const message = fieldErrors[field];
        if (message) {
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
          Create your account
        </h1>
        <p className="mt-2 text-sm text-muted-foreground sm:text-base">
          Join AgentVox and launch your AI interview command center.
        </p>
      </div>

      <SocialLogin disabled={isLoading} showGitHub={false} />

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
          <Label htmlFor="fullName">Full Name</Label>
          <div className="relative">
            <UserRound
              className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <Input
              id="fullName"
              type="text"
              autoComplete="name"
              placeholder="Alex Johnson"
              disabled={isLoading}
              aria-invalid={Boolean(errors.fullName) || undefined}
              aria-describedby={errors.fullName ? "fullName-error" : undefined}
              className="pl-10"
              {...register("fullName")}
            />
          </div>
          {errors.fullName ? (
            <p
              id="fullName-error"
              role="alert"
              className="text-xs text-destructive"
            >
              {errors.fullName.message}
            </p>
          ) : null}
        </div>

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
          <Label htmlFor="password">Password</Label>
          <PasswordInput
            id="password"
            autoComplete="new-password"
            placeholder="••••••••"
            disabled={isLoading}
            error={Boolean(errors.password)}
            aria-describedby={
              errors.password ? "password-error password-strength" : "password-strength"
            }
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
          <div id="password-strength">
            <PasswordStrength password={password} />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="confirmPassword">Confirm Password</Label>
          <PasswordInput
            id="confirmPassword"
            autoComplete="new-password"
            placeholder="••••••••"
            disabled={isLoading}
            error={Boolean(errors.confirmPassword)}
            aria-describedby={
              errors.confirmPassword ? "confirmPassword-error" : undefined
            }
            {...register("confirmPassword")}
          />
          {errors.confirmPassword ? (
            <p
              id="confirmPassword-error"
              role="alert"
              className="text-xs text-destructive"
            >
              {errors.confirmPassword.message}
            </p>
          ) : null}
        </div>

        <div className="space-y-3">
          <Controller
            control={control}
            name="acceptTerms"
            render={({ field }) => (
              <div className="flex items-start gap-2.5">
                <Checkbox
                  id="acceptTerms"
                  checked={field.value}
                  disabled={isLoading}
                  onCheckedChange={(checked) => field.onChange(checked)}
                  aria-invalid={Boolean(errors.acceptTerms) || undefined}
                  aria-describedby={
                    errors.acceptTerms ? "acceptTerms-error" : undefined
                  }
                  className="mt-0.5"
                />
                <div>
                  <Label
                    htmlFor="acceptTerms"
                    className="cursor-pointer normal-case tracking-normal text-sm font-medium text-white"
                  >
                    I accept the{" "}
                    <Link
                      href="/privacy"
                      className="text-primary hover:text-primary/80"
                    >
                      Terms & Conditions
                    </Link>
                  </Label>
                  {errors.acceptTerms ? (
                    <p
                      id="acceptTerms-error"
                      role="alert"
                      className="mt-1 text-xs text-destructive"
                    >
                      {errors.acceptTerms.message}
                    </p>
                  ) : null}
                </div>
              </div>
            )}
          />

          <Controller
            control={control}
            name="receiveUpdates"
            render={({ field }) => (
              <div className="flex items-start gap-2.5">
                <Checkbox
                  id="receiveUpdates"
                  checked={field.value}
                  disabled={isLoading}
                  onCheckedChange={(checked) => field.onChange(checked)}
                  className="mt-0.5"
                />
                <Label
                  htmlFor="receiveUpdates"
                  className="cursor-pointer normal-case tracking-normal text-sm font-medium text-white"
                >
                  Receive product updates (optional)
                </Label>
              </div>
            )}
          />
        </div>

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
                Creating account...
              </>
            ) : (
              <>
                Create Account
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </>
            )}
          </Button>
        </motion.div>
      </form>

      <p className="mt-6 text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link
          href="/login"
          className={cn(
            buttonVariants({ variant: "link" }),
            "h-auto p-0 text-sm font-semibold text-primary"
          )}
        >
          Login
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
