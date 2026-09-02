"use client";

import { create } from "zustand";

import type { SettingsSection } from "@/features/settings/types/settings.types";

interface SettingsStore {
  activeSection: SettingsSection;
  setActiveSection: (section: SettingsSection) => void;
  statusMessage: string | null;
  setStatusMessage: (message: string | null) => void;
}

export const useSettingsStore = create<SettingsStore>((set) => ({
  activeSection: "profile",
  setActiveSection: (section) => set({ activeSection: section }),
  statusMessage: null,
  setStatusMessage: (message) => set({ statusMessage: message }),
}));
