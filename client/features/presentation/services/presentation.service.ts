"use client";

import { candidateService } from "@/features/candidate/services/candidate.service";
import type {
  PresentationCandidateLookup,
  PresentationDashboard,
  PresentationReportLookup,
} from "@/features/presentation/types/presentation.types";
import {
  mapPresentationCandidateLookup,
  mapPresentationDashboard,
  mapPresentationReportLookup,
} from "@/features/presentation/utils/presentation-mappers";
import { reportService } from "@/features/report/services/report.service";
import { api } from "@/services/api/client";

export const presentationService = {
  async getPresentation(candidateId: string): Promise<PresentationDashboard> {
    const data = await api.get<unknown>(`/presentation/${candidateId}`);
    return mapPresentationDashboard(data);
  },

  async getReport(id: string): Promise<PresentationReportLookup> {
    const report = await reportService.getReport(id);
    return mapPresentationReportLookup(report);
  },

  async getCandidate(id: string): Promise<PresentationCandidateLookup> {
    const dossier = await candidateService.getCandidate(id);
    return mapPresentationCandidateLookup(dossier);
  },
};
