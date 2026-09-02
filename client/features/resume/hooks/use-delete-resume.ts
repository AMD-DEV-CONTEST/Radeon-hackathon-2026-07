"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  RESUME_MUTATION_KEYS,
  RESUME_QUERY_KEYS,
} from "@/features/resume/constants/resume-keys";
import { resumeService } from "@/features/resume/services/resume.service";
import { useResumeStore } from "@/features/resume/store/resume.store";
import { getResumeErrorMessage } from "@/features/resume/utils/resume-errors";

export function useDeleteResume() {
  const queryClient = useQueryClient();
  const clearResume = useResumeStore((state) => state.clearResume);
  const currentResume = useResumeStore((state) => state.currentResume);

  return useMutation({
    mutationKey: RESUME_MUTATION_KEYS.delete,
    retry: false,
    mutationFn: async (resumeId?: string) => {
      const id = resumeId ?? currentResume?.id;
      if (!id) {
        throw new Error("No resume selected to remove.");
      }
      return resumeService.deleteResume(id);
    },
    onSuccess: async (_data, resumeId) => {
      const id = resumeId ?? currentResume?.id;
      clearResume();
      if (id) {
        queryClient.removeQueries({ queryKey: RESUME_QUERY_KEYS.detail(id) });
      }
    },
  });
}

export function getDeleteResumeErrorMessage(error: unknown): string {
  return getResumeErrorMessage(error);
}
