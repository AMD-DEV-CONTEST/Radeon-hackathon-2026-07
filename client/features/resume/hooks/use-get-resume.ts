"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { RESUME_QUERY_KEYS } from "@/features/resume/constants/resume-keys";
import { resumeService } from "@/features/resume/services/resume.service";
import { useResumeStore } from "@/features/resume/store/resume.store";

export function useGetResume(resumeId: string | null | undefined) {
  const setCurrentResume = useResumeStore((state) => state.setCurrentResume);

  const query = useQuery({
    queryKey: RESUME_QUERY_KEYS.detail(resumeId ?? "unknown"),
    queryFn: () => {
      if (!resumeId) {
        throw new Error("Resume id is required");
      }
      return resumeService.getResume(resumeId);
    },
    enabled: Boolean(resumeId),
    retry: 1,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (query.data) {
      setCurrentResume(query.data);
    }
  }, [query.data, setCurrentResume]);

  return query;
}
