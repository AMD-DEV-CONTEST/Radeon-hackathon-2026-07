export type DocumentCategory =
  | 'Projects'
  | 'Certificates'
  | 'Internships'
  | 'Achievements'
  | 'Research'
  | 'Hackathons'
  | 'Academics'
  | 'Skills'
  | 'Resume';

export interface DocumentItem {
  id: string;
  title: string;
  fileName: string;
  fileType: 'pdf' | 'docx' | 'image' | 'zip';
  fileSize: string;
  uploadDate: string;
  category: DocumentCategory;
  organization: string;
  issueDate: string;
  summary: string;
  extractedText: string;
  skills: string[];
  embeddingVectorSim?: number;
  relatedDocIds: string[];
  status: 'processed' | 'processing' | 'failed';
  downloadUrl?: string;
}

export interface UserProfile {
  id: string;
  name: string;
  email: string;
  title: string;
  university: string;
  degree: string;
  graduationYear: string;
  targetRole: string;
  avatarUrl: string;
  bio: string;
  skills: string[];
  token?: string;
}

export interface GraphNode {
  id: string;
  label: string;
  type: 'certificate' | 'skill' | 'project' | 'internship' | 'goal' | 'academic';
  category?: string;
  docId?: string;
  description?: string;
  x?: number;
  y?: number;
}

export interface GraphLink {
  source: string;
  target: string;
  label: string;
}

export interface TimelineEventItem {
  id: string;
  year: string;
  date: string;
  title: string;
  category: DocumentCategory;
  organization: string;
  description: string;
  skills: string[];
  docId?: string;
  iconType?: string;
}

export interface CareerInsightsData {
  atsScore: number;
  atsBreakdown: {
    keywordsScore: number;
    formattingScore: number;
    impactMetricsScore: number;
    relevanceScore: number;
  };
  topSkills: { name: string; level: number; docCount: number }[];
  missingSkills: { name: string; importance: 'High' | 'Medium' | 'Low'; reason: string }[];
  recommendedCareers: {
    title: string;
    matchPercentage: number;
    description: string;
    demandLevel: 'High' | 'Very High' | 'Moderate';
  }[];
  suggestedCertifications: {
    title: string;
    provider: string;
    estimatedHours: string;
    skillsCovered: string[];
  }[];
  learningRoadmap: {
    phase: string;
    duration: string;
    title: string;
    description: string;
    actionItems: string[];
  }[];
  weakAreas: string[];
  improvementTips: string[];
}

export interface ChatMessageItem {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  timestamp: string;
  sources?: { docId: string; title: string; snippet: string }[];
  isLoading?: boolean;
}

export interface AppNotification {
  id: string;
  title: string;
  message: string;
  timestamp: string;
  type: 'ai' | 'upload' | 'insight' | 'system';
  read: boolean;
}
