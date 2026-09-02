"use client";

import { create } from "zustand";

import type { ResumeRecord } from "@/features/resume/types/resume.types";

interface ResumeState {
  currentResume: ResumeRecord | null;
  setCurrentResume: (resume: ResumeRecord | null) => void;
  clearResume: () => void;
}

export const useResumeStore = create<ResumeState>((set) => ({
  currentResume: null,
  setCurrentResume: (resume) => {
    set({ currentResume: resume });
  },
  clearResume: () => {
    set({ currentResume: null });
  },
}));
