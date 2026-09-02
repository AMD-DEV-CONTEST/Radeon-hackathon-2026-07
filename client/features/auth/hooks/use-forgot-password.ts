"use client";

import { useMutation } from "@tanstack/react-query";

import { AUTH_MUTATION_KEYS } from "@/features/auth/constants/auth-keys";
import type { ForgotPasswordFormValues } from "@/features/auth/schemas/forgot-password.schema";
import { authService } from "@/features/auth/services/auth.service";
import {
  getAuthErrorMessage,
  getAuthFieldErrors,
} from "@/features/auth/utils/auth-errors";

export function useForgotPassword() {
  return useMutation({
    mutationKey: AUTH_MUTATION_KEYS.forgotPassword,
    retry: false,
    mutationFn: async (values: ForgotPasswordFormValues) => {
      return authService.forgotPassword({
        email: values.email,
      });
    },
  });
}

export function getForgotPasswordErrorMessage(error: unknown): string {
  return getAuthErrorMessage(error);
}

export function getForgotPasswordFieldErrors(
  error: unknown
): Record<string, string> {
  return getAuthFieldErrors(error);
}
