"use client";

import { motion } from "framer-motion";
import { ArrowLeft, CheckCircle2, Mail } from "lucide-react";
import Link from "next/link";

import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ForgotPasswordSuccessProps {
  email: string;
  message: string;
  isResending: boolean;
  onResend: () => void;
}

export function ForgotPasswordSuccess({
  email,
  message,
  isResending,
  onResend,
}: ForgotPasswordSuccessProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 18, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.45, ease: "easeOut" }}
      className="mx-auto w-full max-w-md"
      role="status"
      aria-live="polite"
    >
      <div className="mb-8 text-center sm:text-left">
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.35, delay: 0.1 }}
          className="mb-5 inline-flex h-14 w-14 items-center justify-center rounded-2xl border border-emerald-400/30 bg-emerald-500/10 text-emerald-300"
          aria-hidden="true"
        >
          <CheckCircle2 className="h-7 w-7" />
        </motion.div>
        <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
          Password reset email sent
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground sm:text-base">
          {message}{" "}
          <span className="font-medium text-white">{email}</span>
        </p>
      </div>

      <div className="space-y-3">
        <Link
          href="/login"
          className={cn(
            buttonVariants({ size: "lg" }),
            "h-11 w-full glow-purple"
          )}
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Back to Login
        </Link>

        <motion.div whileHover={{ scale: isResending ? 1 : 1.01 }} whileTap={{ scale: isResending ? 1 : 0.99 }}>
          <Button
            type="button"
            variant="outline"
            className="h-11 w-full border-border bg-[#0b1220] text-white hover:bg-muted"
            disabled={isResending}
            aria-busy={isResending}
            onClick={onResend}
          >
            <Mail className="h-4 w-4" aria-hidden="true" />
            {isResending ? "Resending..." : "Resend Email"}
          </Button>
        </motion.div>
      </div>

      <p className="mt-6 text-center text-sm text-muted-foreground">
        Didn&apos;t get the email? Check spam or{" "}
        <button
          type="button"
          className="font-semibold text-primary hover:text-primary/80"
          disabled={isResending}
          onClick={onResend}
        >
          resend the link
        </button>
        .
      </p>
    </motion.div>
  );
}
