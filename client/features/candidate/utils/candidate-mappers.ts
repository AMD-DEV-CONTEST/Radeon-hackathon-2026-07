import type {
  AnalysisStatus,
  AnalyzeResumeResponse,
  CandidateDossier,
  CandidateProfile,
  CertificationItem,
  CompetencyScore,
  EducationItem,
  ExperienceItem,
  InterviewRoadmap,
  MetricItem,
  ProjectItem,
  ResumeDetails,
  RoadmapDifficulty,
  RoadmapQuestion,
  RoadmapSection,
  SkillItem,
  UpdateCandidateRequest,
} from "@/features/candidate/types/candidate.types";
import type { ResumeRecord } from "@/features/resume/types/resume.types";
import type { BackendResumeDto } from "@/features/resume/utils/resume-mappers";

export interface BackendCandidateDto {
  id: string;
  user_id?: string;
  name?: string;
  full_name?: string;
  email: string;
  phone?: string | null;
  title?: string | null;
  level?: string | null;
  location?: string | null;
  avatar_url?: string | null;
  target_role?: string | null;
  years_of_experience?: number | null;
  skills?: unknown;
  score?: number | null;
  recommendation?: string | null;
  resume_id?: string | null;
  summary?: string | null;
  experience?: unknown;
  projects?: unknown;
  education?: unknown;
  certifications?: unknown;
  core_competencies?: unknown;
  competencies?: unknown;
  strengths?: unknown;
  weaknesses?: unknown;
  ai_summary?: string | null;
  experience_summary?: string | null;
  education_summary?: string | null;
  suggested_interview_focus?: unknown;
  analysis_status?: string | null;
  roadmap?: unknown;
  analysis?: BackendAnalysisDto | null;
  created_at?: string;
  updated_at?: string;
}

export interface BackendAnalysisDto {
  analysis_id?: string;
  id?: string;
  status?: string;
  candidate_id?: string;
  skills?: unknown;
  experience_summary?: string | null;
  education_summary?: string | null;
  suggested_interview_focus?: unknown;
  core_competencies?: unknown;
  experience?: unknown;
  projects?: unknown;
  education?: unknown;
  certifications?: unknown;
  competencies?: unknown;
  strengths?: unknown;
  weaknesses?: unknown;
  ai_summary?: string | null;
  roadmap?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function asString(value: unknown, fallback = ""): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return fallback;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => asString(item).trim())
    .filter((item) => item.length > 0);
}

function compactMap<T>(
  values: ReadonlyArray<T | null>
): T[] {
  return values.filter((value): value is T => value !== null);
}

function getInitials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return "AV";
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase();
}

function mapSkills(value: unknown): SkillItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item) => {
      if (typeof item === "string") {
        const name = item.trim();
        if (!name) {
          return null;
        }
        return {
          name,
          category: "General",
        };
      }

      if (!isRecord(item)) {
        return null;
      }

      const name = asString(item.name ?? item.skill).trim();
      if (!name) {
        return null;
      }

      const proficiencyRaw = item.proficiency ?? item.score ?? item.level;
      const proficiency =
        proficiencyRaw === undefined || proficiencyRaw === null
          ? undefined
          : asNumber(proficiencyRaw);

      return {
        name,
        proficiency,
        category: asString(item.category, "General") || "General",
      };
    })
  );
}

function mapExperience(value: unknown): ExperienceItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      return {
        id: asString(item.id, `exp-${index}`),
        role: asString(item.role ?? item.title),
        company: asString(item.company ?? item.organization),
        startDate: asString(item.start_date ?? item.startDate),
        endDate: asString(item.end_date ?? item.endDate, "Present"),
        description: asString(item.description ?? item.summary),
        highlights: asStringArray(item.highlights ?? item.achievements),
      };
    })
  );
}

function mapProjects(value: unknown): ProjectItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      return {
        id: asString(item.id, `proj-${index}`),
        name: asString(item.name ?? item.title),
        role: asString(item.role),
        description: asString(item.description ?? item.summary),
        technologies: asStringArray(item.technologies ?? item.tech_stack),
      };
    })
  );
}

function mapEducation(value: unknown): EducationItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      return {
        id: asString(item.id, `edu-${index}`),
        degree: asString(item.degree ?? item.name),
        institution: asString(item.institution ?? item.school),
        year: asString(item.year ?? item.end_year ?? item.endYear),
        details: asString(item.details ?? item.description),
      };
    })
  );
}

function mapCertifications(value: unknown): CertificationItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      return {
        id: asString(item.id, `cert-${index}`),
        name: asString(item.name ?? item.title),
        issuer: asString(item.issuer ?? item.organization),
        year: asString(item.year),
      };
    })
  );
}

function mapCompetencies(value: unknown): CompetencyScore[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item) => {
      if (!isRecord(item)) {
        return null;
      }

      const subject = asString(item.subject ?? item.name).trim();
      if (!subject) {
        return null;
      }

      return {
        subject,
        candidate: asNumber(item.candidate ?? item.score ?? item.value),
        required: asNumber(item.required ?? item.benchmark, 0),
      };
    })
  );
}

function mapMetrics(value: unknown): MetricItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item) => {
      if (!isRecord(item)) {
        return null;
      }

      const label = asString(item.label ?? item.name).trim();
      if (!label) {
        return null;
      }

      return {
        label,
        score: asNumber(item.score ?? item.value),
        description: asString(item.description ?? item.summary),
      };
    })
  );
}

function mapDifficulty(value: unknown): RoadmapDifficulty {
  const normalized = asString(value).toLowerCase();
  if (normalized === "high") {
    return "High";
  }
  if (normalized === "low") {
    return "Low";
  }
  return "Med";
}

function mapRoadmapQuestions(value: unknown): RoadmapQuestion[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      const prompt = asString(item.prompt ?? item.question).trim();
      if (!prompt) {
        return null;
      }

      return {
        id: asString(item.id, `q-${index}`),
        category: asString(item.category, "General"),
        difficulty: mapDifficulty(item.difficulty),
        prompt,
      };
    })
  );
}

function mapRoadmapSections(value: unknown): RoadmapSection[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      return {
        id: asString(item.id, `section-${index}`),
        title: asString(item.title, `Section ${index + 1}`),
        questions: mapRoadmapQuestions(item.questions),
      };
    })
  );
}

function mapRoadmap(
  value: unknown,
  fallbackTargetRole: string,
  recommendedFocus: ReadonlyArray<string>
): InterviewRoadmap {
  if (!isRecord(value)) {
    return {
      durationMinutes: 0,
      targetRole: fallbackTargetRole,
      complexity: "",
      readinessScore: 0,
      recommendedFocus,
      sections: [],
    };
  }

  const focus = asStringArray(
    value.recommended_focus ?? value.recommendedFocus
  );

  return {
    durationMinutes: asNumber(value.duration_minutes ?? value.durationMinutes),
    targetRole: asString(value.target_role ?? value.targetRole, fallbackTargetRole),
    complexity: asString(value.complexity),
    readinessScore: asNumber(
      value.readiness_score ?? value.readinessScore ?? value.score
    ),
    recommendedFocus: focus.length > 0 ? focus : [...recommendedFocus],
    sections: mapRoadmapSections(value.sections),
  };
}

function mapAnalysisStatus(value: unknown): AnalysisStatus {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "complete" ||
    normalized === "completed" ||
    normalized === "analyzed" ||
    normalized === "success"
  ) {
    return "complete";
  }
  if (
    normalized === "failed" ||
    normalized === "error" ||
    normalized === "failure"
  ) {
    return "failed";
  }
  if (
    normalized === "pending" ||
    normalized === "queued" ||
    normalized === "processing" ||
    normalized === "running"
  ) {
    return "pending";
  }
  return "idle";
}

function extractParsedData(dto: BackendResumeDto): Record<string, unknown> | null {
  if (isRecord(dto.parsed_data)) {
    return dto.parsed_data;
  }
  return null;
}

export function mapCandidateProfile(
  dto: BackendCandidateDto,
  resumeIdFallback: string | null = null
): CandidateProfile {
  const fullName = asString(dto.full_name ?? dto.name).trim() || dto.email;
  const targetRole = asString(dto.target_role ?? dto.title);
  const title = asString(dto.title ?? dto.target_role ?? dto.level);

  return {
    id: String(dto.id),
    resumeId: dto.resume_id ? String(dto.resume_id) : resumeIdFallback,
    fullName,
    title,
    email: dto.email,
    phone: dto.phone ?? null,
    location: asString(dto.location),
    avatarInitials: getInitials(fullName),
    summary: asString(dto.summary ?? dto.ai_summary ?? dto.experience_summary),
    yearsOfExperience: asNumber(dto.years_of_experience),
    targetRole,
  };
}

export function mapCandidateDossier(
  dto: BackendCandidateDto,
  options: {
    resumeId?: string | null;
    analysis?: BackendAnalysisDto | null;
  } = {}
): CandidateDossier {
  const analysis = options.analysis ?? dto.analysis ?? null;
  const profile = mapCandidateProfile(dto, options.resumeId ?? null);

  const skills = mapSkills(analysis?.skills ?? dto.skills);
  const coreCompetencies = asStringArray(
    analysis?.core_competencies ?? dto.core_competencies ?? dto.skills
  );
  const experience = mapExperience(analysis?.experience ?? dto.experience);
  const projects = mapProjects(analysis?.projects ?? dto.projects);
  const education = mapEducation(analysis?.education ?? dto.education);
  const certifications = mapCertifications(
    analysis?.certifications ?? dto.certifications
  );
  const suggestedInterviewFocus = asStringArray(
    analysis?.suggested_interview_focus ?? dto.suggested_interview_focus
  );
  const experienceSummary = asString(
    analysis?.experience_summary ?? dto.experience_summary
  );
  const educationSummary = asString(
    analysis?.education_summary ?? dto.education_summary
  );
  const aiSummary = asString(
    analysis?.ai_summary ?? dto.ai_summary ?? experienceSummary
  );
  const roadmap = mapRoadmap(
    analysis?.roadmap ?? dto.roadmap,
    profile.targetRole,
    suggestedInterviewFocus
  );

  const analysisStatus = mapAnalysisStatus(
    analysis?.status ?? dto.analysis_status
  );

  return {
    profile: {
      ...profile,
      summary:
        profile.summary ||
        experienceSummary ||
        educationSummary ||
        aiSummary,
    },
    skills,
    coreCompetencies:
      coreCompetencies.length > 0
        ? coreCompetencies
        : skills.map((skill) => skill.name),
    experience,
    projects,
    education,
    certifications,
    competencies: mapCompetencies(analysis?.competencies ?? dto.competencies),
    strengths: mapMetrics(analysis?.strengths ?? dto.strengths),
    weaknesses: mapMetrics(analysis?.weaknesses ?? dto.weaknesses),
    aiSummary,
    experienceSummary,
    educationSummary,
    suggestedInterviewFocus:
      suggestedInterviewFocus.length > 0
        ? suggestedInterviewFocus
        : roadmap.recommendedFocus,
    roadmap,
    analysisStatus:
      analysisStatus === "idle" &&
      (aiSummary || skills.length > 0 || experienceSummary)
        ? "complete"
        : analysisStatus,
  };
}

export function mapAnalyzeResumeResponse(
  dto: BackendAnalysisDto
): AnalyzeResumeResponse {
  const suggestedInterviewFocus = asStringArray(
    dto.suggested_interview_focus
  );
  const experienceSummary = asString(dto.experience_summary);
  const educationSummary = asString(dto.education_summary);
  const aiSummary = asString(dto.ai_summary ?? experienceSummary);
  const skills = mapSkills(dto.skills);
  const coreCompetencies = asStringArray(dto.core_competencies);
  const statusRaw = asString(dto.status, "complete").toLowerCase();
  const status: AnalyzeResumeResponse["status"] =
    statusRaw === "queued" ||
    statusRaw === "processing" ||
    statusRaw === "failed"
      ? statusRaw
      : "complete";

  const roadmap = mapRoadmap(dto.roadmap, "", suggestedInterviewFocus);

  return {
    analysisId: asString(dto.analysis_id ?? dto.id),
    status,
    candidateId: asString(dto.candidate_id),
    skills,
    experienceSummary,
    educationSummary,
    suggestedInterviewFocus,
    coreCompetencies:
      coreCompetencies.length > 0
        ? coreCompetencies
        : skills.map((skill) => skill.name),
    experience: mapExperience(dto.experience),
    projects: mapProjects(dto.projects),
    education: mapEducation(dto.education),
    certifications: mapCertifications(dto.certifications),
    competencies: mapCompetencies(dto.competencies),
    strengths: mapMetrics(dto.strengths),
    weaknesses: mapMetrics(dto.weaknesses),
    aiSummary,
    roadmap,
  };
}

export function mapResumeDetails(
  record: ResumeRecord,
  dto?: BackendResumeDto
): ResumeDetails {
  const parsed = dto ? extractParsedData(dto) : null;
  const parsedSummary = asString(
    parsed?.summary ?? parsed?.parsed_summary ?? record.candidate.targetRole
  );

  return {
    id: record.id,
    candidateId: record.candidateId,
    fileName: record.fileName,
    uploadedAt: record.uploadedAt,
    fileSize: record.fileSize,
    status: record.status,
    mimeType: record.mimeType,
    parsedSummary,
  };
}

export function toBackendCandidateUpdate(
  payload: UpdateCandidateRequest
): Record<string, string | number | string[] | null> {
  const body: Record<string, string | number | string[] | null> = {};

  if (payload.fullName !== undefined) {
    body.name = payload.fullName;
    body.full_name = payload.fullName;
  }
  if (payload.email !== undefined) {
    body.email = payload.email;
  }
  if (payload.phone !== undefined) {
    body.phone = payload.phone;
  }
  if (payload.title !== undefined) {
    body.title = payload.title;
  }
  if (payload.targetRole !== undefined) {
    body.target_role = payload.targetRole;
  }
  if (payload.yearsOfExperience !== undefined) {
    body.years_of_experience = payload.yearsOfExperience;
  }
  if (payload.skills !== undefined) {
    body.skills = payload.skills ? [...payload.skills] : null;
  }

  return body;
}

export function mergeAnalysisIntoDossier(
  dossier: CandidateDossier,
  analysis: AnalyzeResumeResponse
): CandidateDossier {
  return {
    ...dossier,
    skills: analysis.skills.length > 0 ? analysis.skills : dossier.skills,
    coreCompetencies:
      analysis.coreCompetencies.length > 0
        ? analysis.coreCompetencies
        : dossier.coreCompetencies,
    experience:
      analysis.experience.length > 0 ? analysis.experience : dossier.experience,
    projects:
      analysis.projects.length > 0 ? analysis.projects : dossier.projects,
    education:
      analysis.education.length > 0 ? analysis.education : dossier.education,
    certifications:
      analysis.certifications.length > 0
        ? analysis.certifications
        : dossier.certifications,
    competencies:
      analysis.competencies.length > 0
        ? analysis.competencies
        : dossier.competencies,
    strengths:
      analysis.strengths.length > 0 ? analysis.strengths : dossier.strengths,
    weaknesses:
      analysis.weaknesses.length > 0 ? analysis.weaknesses : dossier.weaknesses,
    aiSummary: analysis.aiSummary || dossier.aiSummary,
    experienceSummary:
      analysis.experienceSummary || dossier.experienceSummary,
    educationSummary: analysis.educationSummary || dossier.educationSummary,
    suggestedInterviewFocus:
      analysis.suggestedInterviewFocus.length > 0
        ? analysis.suggestedInterviewFocus
        : dossier.suggestedInterviewFocus,
    roadmap: {
      ...dossier.roadmap,
      ...analysis.roadmap,
      recommendedFocus:
        analysis.suggestedInterviewFocus.length > 0
          ? analysis.suggestedInterviewFocus
          : analysis.roadmap.recommendedFocus.length > 0
            ? analysis.roadmap.recommendedFocus
            : dossier.roadmap.recommendedFocus,
    },
    analysisStatus:
      analysis.status === "failed"
        ? "failed"
        : analysis.status === "complete"
          ? "complete"
          : "pending",
    profile: {
      ...dossier.profile,
      summary:
        analysis.experienceSummary ||
        analysis.aiSummary ||
        dossier.profile.summary,
    },
  };
}
