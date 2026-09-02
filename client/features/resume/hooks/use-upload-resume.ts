"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";

import {
  RESUME_MUTATION_KEYS,
  RESUME_QUERY_KEYS,
} from "@/features/resume/constants/resume-keys";
import { resumeService } from "@/features/resume/services/resume.service";
import { useResumeStore } from "@/features/resume/store/resume.store";
import type {
  ResumeRecord,
  UploadProgressState,
  UploadResumePayload,
  UploadResumeResponse,
} from "@/features/resume/types/resume.types";
import { getResumeErrorMessage } from "@/features/resume/utils/resume-errors";

const initialProgressState: UploadProgressState = {
  status: "idle",
  progress: 0,
  errorMessage: null,
};

function toResumeRecord(response: UploadResumeResponse): ResumeRecord {
  return {
    id: response.id,
    fileName: response.fileName,
    fileSize: response.fileSize,
    mimeType: response.mimeType,
    status: "uploaded",
    uploadedAt: response.uploadedAt,
    candidateId: "",
    candidate: response.candidate,
  };
}

export function useUploadResume() {
  const queryClient = useQueryClient();
  const setCurrentResume = useResumeStore((state) => state.setCurrentResume);
  const [progressState, setProgressState] =
    useState<UploadProgressState>(initialProgressState);
  const lastPayloadRef = useRef<UploadResumePayload | null>(null);

  const resetProgress = useCallback(() => {
    setProgressState(initialProgressState);
  }, []);

  const mutation = useMutation<
    UploadResumeResponse,
    unknown,
    UploadResumePayload
  >({
    mutationKey: RESUME_MUTATION_KEYS.upload,
    retry: false,
    mutationFn: async (payload) => {
      lastPayloadRef.current = payload;
      setProgressState({
        status: "uploading",
        progress: 0,
        errorMessage: null,
      });

      try {
        const response = await resumeService.uploadResume(payload, {
          onProgress: (progress) => {
            setProgressState((previous) => ({
              ...previous,
              status: "uploading",
              progress,
              errorMessage: null,
            }));
          },
        });

        setProgressState({
          status: "success",
          progress: 100,
          errorMessage: null,
        });

        return response;
      } catch (error) {
        setProgressState({
          status: "error",
          progress: 0,
          errorMessage: getResumeErrorMessage(error),
        });
        throw error;
      }
    },
    onSuccess: async (data) => {
      const record = toResumeRecord(data);
      setCurrentResume(record);
      queryClient.setQueryData(RESUME_QUERY_KEYS.detail(data.id), record);
      await queryClient.invalidateQueries({
        queryKey: RESUME_QUERY_KEYS.detail(data.id),
      });
    },
  });

  const retryUpload = useCallback(async () => {
    const payload = lastPayloadRef.current;
    if (!payload || mutation.isPending) {
      return;
    }
    return mutation.mutateAsync(payload);
  }, [mutation]);

  return {
    ...mutation,
    progressState,
    resetProgress,
    retryUpload,
    lastPayload: lastPayloadRef.current,
    isUploading: mutation.isPending || progressState.status === "uploading",
  };
}
