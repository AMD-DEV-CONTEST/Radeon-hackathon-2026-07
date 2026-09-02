"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Loader2, Mail } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ForgotPasswordSuccess } from "@/features/auth/components/forgot-password-success";
import {
  getForgotPasswordErrorMessage,
  getForgotPasswordFieldErrors,
  useForgotPassword,
} from "@/features/auth/hooks/use-forgot-password";
import {
  forgotPasswordSchema,
  type ForgotPasswordFormValues,
} from "@/features/auth/schemas/forgot-password.schema";
import { cn } from "@/lib/utils";

export function ForgotPasswordForm() {
  const forgotPasswordMutation = useForgotPassword();
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setError,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<ForgotPasswordFormValues>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: {
      email: "",
    },
    mode: "onSubmit",
  });

  const isLoading = isSubmitting || forgotPasswordMutation.isPending;
  const serverError =
    !submittedEmail && forgotPasswordMutation.error
      ? getForgotPasswordErrorMessage(forgotPasswordMutation.error)
      : null;

  const onSubmit = handleSubmit(async (values) => {
    if (isLoading) {
      return;
    }

    try {
      const response = await forgotPasswordMutation.mutateAsync(values);
      setSuccessMessage(response.message);
      setSubmittedEmail(values.email);
    } catch (error) {
      const fieldErrors = getForgotPasswordFieldErrors(error);
      if (fieldErrors.email) {
        setError("email", { type: "server", message: fieldErrors.email });
      }
    }
  });

  async function handleResend() {
    const email = submittedEmail ?? getValues("email");
    if (!email || isLoading) {
      return;
    }

    try {
      const response = await forgotPasswordMutation.mutateAsync({ email });
      setSuccessMessage(response.message);
      setSubmittedEmail(email);
    } catch {
      // Keep success card visible; error surfaces via mutation state below if needed
    }
  }

  return (
    <AnimatePresence mode="wait">
      {submittedEmail && successMessage ? (
        <ForgotPasswordSuccess
          key="success"
          email={submittedEmail}
          message={successMessage}
          isResending={forgotPasswordMutation.isPending}
          onResend={() => {
            void handleResend();
          }}
        />
      ) : (
        <motion.div
          key="form"
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.45, ease: "easeOut" }}
          className="mx-auto w-full max-w-md"
        >
          <div className="mb-8">
            <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Forgot password?
            </h1>
            <p className="mt-2 text-sm text-muted-foreground sm:text-base">
              Enter your work email and we&apos;ll send you a secure reset link.
            </p>
          </div>

          <form className="space-y-5" onSubmit={onSubmit} noValidate>
            <div className="space-y-2">
              <Label htmlFor="email">Email Address</Label>
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
                <p
                  id="email-error"
                  role="alert"
                  className="text-xs text-destructive"
                >
                  {errors.email.message}
                </p>
              ) : null}
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
                    <Loader2
                      className="h-4 w-4 animate-spin"
                      aria-hidden="true"
                    />
                    Sending reset link...
                  </>
                ) : (
                  <>
                    Send Reset Link
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </>
                )}
              </Button>
            </motion.div>
          </form>

          <div className="mt-6 flex flex-col items-center gap-3 text-sm text-muted-foreground sm:flex-row sm:justify-between">
            <Link
              href="/login"
              className={cn(
                buttonVariants({ variant: "link" }),
                "h-auto gap-1.5 p-0 text-sm font-semibold text-primary"
              )}
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
              Back to Login
            </Link>
            <p>
              Need an account?{" "}
              <Link
                href="/register"
                className={cn(
                  buttonVariants({ variant: "link" }),
                  "h-auto p-0 text-sm font-semibold text-primary"
                )}
              >
                Create Account
              </Link>
            </p>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
