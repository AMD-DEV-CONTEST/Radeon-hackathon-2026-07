"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { motion } from "framer-motion";
import {
  Briefcase,
  CalendarDays,
  Loader2,
  Mail,
  Upload,
  UserRound,
} from "lucide-react";
import { Controller, useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { UploadDropzone } from "@/features/resume/components/upload-dropzone";
import { UploadProgress } from "@/features/resume/components/upload-progress";
import { useDeleteResume } from "@/features/resume/hooks/use-delete-resume";
import { useGetResume } from "@/features/resume/hooks/use-get-resume";
import { useUploadResume } from "@/features/resume/hooks/use-upload-resume";
import {
  resumeUploadSchema,
  type ResumeUploadFormValues,
  type ResumeUploadPayloadValues,
} from "@/features/resume/schemas/resume.schema";
import { useResumeStore } from "@/features/resume/store/resume.store";
import {
  getResumeErrorMessage,
  getResumeFieldErrors,
} from "@/features/resume/utils/resume-errors";

type ResumeFormField =
  | "fullName"
  | "email"
  | "targetRole"
  | "yearsOfExperience"
  | "file";

const RESUME_FORM_FIELDS: ReadonlyArray<ResumeFormField> = [
  "fullName",
  "email",
  "targetRole",
  "yearsOfExperience",
  "file",
];

export function UploadCard() {
  const currentResume = useResumeStore((state) => state.currentResume);
  const clearResume = useResumeStore((state) => state.clearResume);

  const {
    mutateAsync,
    isUploading,
    progressState,
    resetProgress,
    retryUpload,
    isSuccess,
    reset: resetMutation,
  } = useUploadResume();

  const deleteResume = useDeleteResume();
  useGetResume(currentResume?.id);

  const {
    register,
    control,
    handleSubmit,
    setError,
    clearErrors,
    watch,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ResumeUploadFormValues, unknown, ResumeUploadPayloadValues>({
    resolver: zodResolver(resumeUploadSchema),
    defaultValues: {
      fullName: "",
      email: "",
      targetRole: "",
      yearsOfExperience: "",
      file: undefined,
    },
    mode: "onSubmit",
  });

  const selectedFile = watch("file");
  const isBusy =
    isUploading || isSubmitting || deleteResume.isPending;

  function applyServerFieldErrors(error: unknown) {
    const fieldErrors = getResumeFieldErrors(error);

    for (const field of RESUME_FORM_FIELDS) {
      const message = fieldErrors[field];
      if (message) {
        setError(field, { type: "server", message });
      }
    }
  }

  const onSubmit = handleSubmit(async (values) => {
    if (isBusy) {
      return;
    }

    try {
      await mutateAsync({
        fullName: values.fullName,
        email: values.email,
        targetRole: values.targetRole,
        yearsOfExperience: values.yearsOfExperience,
        file: values.file,
      });
    } catch (error) {
      applyServerFieldErrors(error);
    }
  });

  async function handleRetry() {
    if (isBusy) {
      return;
    }

    try {
      await retryUpload();
    } catch (error) {
      applyServerFieldErrors(error);
    }
  }

  async function handleRemoveFile(onFileChange: (file: File | null) => void) {
    if (isBusy) {
      return;
    }

    if (currentResume?.id) {
      try {
        await deleteResume.mutateAsync(currentResume.id);
      } catch (error) {
        setError("file", {
          type: "server",
          message: getResumeErrorMessage(error),
        });
        return;
      }
    }

    onFileChange(null);
    resetProgress();
    resetMutation();
  }

  async function handleReplaceFile(openFilePicker: () => void) {
    if (isBusy) {
      return;
    }

    if (currentResume?.id) {
      try {
        await deleteResume.mutateAsync(currentResume.id);
      } catch (error) {
        setError("file", {
          type: "server",
          message: getResumeErrorMessage(error),
        });
        return;
      }
      resetProgress();
      resetMutation();
    }

    openFilePicker();
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-5"
    >
      <Card className="rounded-2xl border border-border/70 bg-[#12121a] py-0 ring-0">
        <CardContent className="p-5 sm:p-6">
          <div className="mb-5 flex items-center gap-2">
            <UserRound className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 className="text-xs font-semibold tracking-[0.16em] text-muted-foreground uppercase">
              Candidate Information
            </h2>
          </div>

          <form className="space-y-5" onSubmit={onSubmit} noValidate>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="fullName">Full Name</Label>
                <div className="relative">
                  <UserRound
                    className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <Input
                    id="fullName"
                    autoComplete="name"
                    placeholder="e.g. Alexander Johnson"
                    disabled={isBusy}
                    aria-invalid={Boolean(errors.fullName) || undefined}
                    className="pl-10"
                    {...register("fullName")}
                  />
                </div>
                {errors.fullName ? (
                  <p role="alert" className="text-xs text-destructive">
                    {errors.fullName.message}
                  </p>
                ) : null}
              </div>

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
                    placeholder="e.g. alex.j@company.com"
                    disabled={isBusy}
                    aria-invalid={Boolean(errors.email) || undefined}
                    className="pl-10"
                    {...register("email")}
                  />
                </div>
                {errors.email ? (
                  <p role="alert" className="text-xs text-destructive">
                    {errors.email.message}
                  </p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="targetRole">Target Role</Label>
                <div className="relative">
                  <Briefcase
                    className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <Input
                    id="targetRole"
                    autoComplete="organization-title"
                    placeholder="e.g. Senior Software Architect"
                    disabled={isBusy}
                    aria-invalid={Boolean(errors.targetRole) || undefined}
                    className="pl-10"
                    {...register("targetRole")}
                  />
                </div>
                {errors.targetRole ? (
                  <p role="alert" className="text-xs text-destructive">
                    {errors.targetRole.message}
                  </p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="yearsOfExperience">Years of Experience</Label>
                <div className="relative">
                  <CalendarDays
                    className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <Input
                    id="yearsOfExperience"
                    type="number"
                    inputMode="numeric"
                    min={0}
                    max={60}
                    placeholder="e.g. 8"
                    disabled={isBusy}
                    aria-invalid={
                      Boolean(errors.yearsOfExperience) || undefined
                    }
                    className="pl-10"
                    {...register("yearsOfExperience")}
                  />
                </div>
                {errors.yearsOfExperience ? (
                  <p role="alert" className="text-xs text-destructive">
                    {errors.yearsOfExperience.message}
                  </p>
                ) : null}
              </div>
            </div>

            <Controller
              control={control}
              name="file"
              render={({ field }) => (
                <UploadDropzone
                  file={field.value instanceof File ? field.value : null}
                  disabled={isBusy}
                  error={errors.file?.message}
                  onFileChange={(nextFile) => {
                    if (progressState.status !== "idle") {
                      resetProgress();
                      resetMutation();
                    }
                    field.onChange(nextFile);
                    if (nextFile) {
                      clearErrors("file");
                    }
                  }}
                  onValidationError={(message) => {
                    if (message) {
                      setError("file", { type: "validate", message });
                      return;
                    }
                    clearErrors("file");
                  }}
                  onRemove={() => {
                    void handleRemoveFile(field.onChange);
                  }}
                  onReplace={(openFilePicker) => {
                    void handleReplaceFile(openFilePicker);
                  }}
                />
              )}
            />

            <UploadProgress
              state={progressState}
              onRetry={() => {
                void handleRetry();
              }}
              isRetrying={isBusy}
            />

            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs text-muted-foreground">
                {selectedFile instanceof File
                  ? `Ready to upload: ${selectedFile.name}`
                  : currentResume
                    ? `Uploaded: ${currentResume.fileName}`
                    : "Select a PDF or DOCX resume to continue."}
              </p>

              <div className="flex items-center gap-2">
                {isSuccess ? (
                  <Button
                    type="button"
                    variant="outline"
                    className="h-10"
                    onClick={() => {
                      reset({
                        fullName: "",
                        email: "",
                        targetRole: "",
                        yearsOfExperience: "",
                        file: undefined,
                      });
                      clearResume();
                      resetProgress();
                      resetMutation();
                    }}
                  >
                    Upload Another
                  </Button>
                ) : null}

                <motion.div
                  whileHover={{ scale: isBusy ? 1 : 1.01 }}
                  whileTap={{ scale: isBusy ? 1 : 0.99 }}
                >
                  <Button
                    type="submit"
                    className="h-10 glow-purple"
                    disabled={isBusy || isSuccess}
                    aria-busy={isUploading || isSubmitting}
                  >
                    {isUploading || isSubmitting ? (
                      <>
                        <Loader2
                          className="h-4 w-4 animate-spin"
                          aria-hidden="true"
                        />
                        Uploading...
                      </>
                    ) : (
                      <>
                        <Upload className="h-4 w-4" aria-hidden="true" />
                        Upload Resume
                      </>
                    )}
                  </Button>
                </motion.div>
              </div>
            </div>
          </form>
        </CardContent>
      </Card>
    </motion.section>
  );
}
