"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { AUTH_MUTATION_KEYS } from "@/features/auth/constants/auth-keys";
import type { RegisterFormValues } from "@/features/auth/schemas/register.schema";
import { authService } from "@/features/auth/services/auth.service";
import {
  getAuthErrorMessage,
  getAuthFieldErrors,
  isDuplicateEmailError,
} from "@/features/auth/utils/auth-errors";

export function useRegister() {
  const router = useRouter();

  return useMutation({
    mutationKey: AUTH_MUTATION_KEYS.register,
    retry: false,
    mutationFn: async (values: RegisterFormValues) => {
      return authService.register({
        fullName: values.fullName,
        email: values.email,
        password: values.password,
        acceptTerms: values.acceptTerms,
        receiveUpdates: values.receiveUpdates,
      });
    },
    onSuccess: () => {
      router.replace("/login");
    },
  });
}

export function getRegisterErrorMessage(error: unknown): string {
  if (isDuplicateEmailError(error)) {
    return "An account with this email already exists. Try signing in instead.";
  }

  return getAuthErrorMessage(error);
}

export function getRegisterFieldErrors(
  error: unknown
): Record<string, string> {
  const fieldErrors = getAuthFieldErrors(error);

  if (isDuplicateEmailError(error) && !fieldErrors.email) {
    return {
      ...fieldErrors,
      email: "This email is already registered",
    };
  }

  return fieldErrors;
}
