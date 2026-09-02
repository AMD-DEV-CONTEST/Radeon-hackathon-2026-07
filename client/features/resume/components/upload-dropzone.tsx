"use client";

import { motion } from "framer-motion";
import { CloudUpload } from "lucide-react";
import {
  useCallback,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type KeyboardEvent,
} from "react";

import { Button } from "@/components/ui/button";
import { ResumePreview } from "@/features/resume/components/resume-preview";
import { validateResumeFile } from "@/features/resume/schemas/resume.schema";
import { cn } from "@/lib/utils";

interface UploadDropzoneProps {
  file: File | null;
  disabled?: boolean;
  error?: string;
  onFileChange: (file: File | null) => void;
  onValidationError: (message: string | null) => void;
  /** Optional override when removing an already-selected/uploaded resume. */
  onRemove?: () => void;
  /** Optional override when replacing; receives the file-picker opener. */
  onReplace?: (openFilePicker: () => void) => void;
}

export function UploadDropzone({
  file,
  disabled = false,
  error,
  onFileChange,
  onValidationError,
  onRemove,
  onReplace,
}: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const [isDragging, setIsDragging] = useState(false);

  const openFilePicker = useCallback(() => {
    if (disabled) {
      return;
    }
    inputRef.current?.click();
  }, [disabled]);

  const applyFile = useCallback(
    (nextFile: File | null) => {
      if (!nextFile) {
        onFileChange(null);
        onValidationError(null);
        return;
      }

      const validationError = validateResumeFile(nextFile);
      if (validationError) {
        onFileChange(null);
        onValidationError(validationError);
        return;
      }

      onFileChange(nextFile);
      onValidationError(null);
    },
    [onFileChange, onValidationError]
  );

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null;
    applyFile(nextFile);
    event.target.value = "";
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);

    if (disabled) {
      return;
    }

    const nextFile = event.dataTransfer.files?.[0] ?? null;
    applyFile(nextFile);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openFilePicker();
    }
  };

  return (
    <div className="space-y-3">
      <motion.div
        onDragEnter={(event) => {
          event.preventDefault();
          if (!disabled) {
            setIsDragging(true);
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) {
            setIsDragging(true);
          }
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          setIsDragging(false);
        }}
        onDrop={handleDrop}
        onKeyDown={handleKeyDown}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-label="Resume upload dropzone. Press Enter to browse files."
        animate={{
          scale: isDragging ? 1.01 : 1,
          borderColor: isDragging
            ? "rgba(139, 92, 246, 0.8)"
            : error
              ? "rgba(239, 68, 68, 0.55)"
              : "rgba(30, 41, 59, 0.9)",
        }}
        transition={{ duration: 0.18 }}
        className={cn(
          "rounded-2xl border border-dashed bg-[#0f1018]/80 px-6 py-10 text-center outline-none transition-colors",
          "focus-visible:ring-2 focus-visible:ring-primary/40",
          isDragging && "bg-primary/5",
          disabled && "cursor-not-allowed opacity-60",
          !disabled && "cursor-pointer"
        )}
        onClick={openFilePicker}
      >
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          className="sr-only"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          disabled={disabled}
          onChange={handleInputChange}
          aria-hidden="true"
          tabIndex={-1}
        />

        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-primary/15 text-primary">
          <CloudUpload className="h-6 w-6" aria-hidden="true" />
        </div>

        <p className="text-base font-semibold text-white sm:text-lg">
          Drag and drop your resume
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          Supported formats: PDF, DOCX (Max 10MB)
        </p>

        <Button
          type="button"
          className="mt-6 h-10 glow-purple"
          disabled={disabled}
          onClick={(event) => {
            event.stopPropagation();
            openFilePicker();
          }}
        >
          Select File from System
        </Button>
      </motion.div>

      {file ? (
        <ResumePreview
          file={file}
          disabled={disabled}
          onRemove={() => {
            if (onRemove) {
              onRemove();
              return;
            }
            applyFile(null);
          }}
          onReplace={() => {
            if (onReplace) {
              onReplace(openFilePicker);
              return;
            }
            openFilePicker();
          }}
        />
      ) : null}

      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
