export interface UserProfile {
  uid: string;
  email: string | null;
  displayName: string | null;
  createdAt: any; // Firestore Timestamp
  age?: number;
  gender?: string;
  healthNotes?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number; // local timestamp
}

export interface ChatSession {
  id: string;
  userId: string;
  title: string;
  createdAt: any; // Firestore Timestamp or Date
  messages: ChatMessage[];
}

export interface SymptomCheckResult {
  id: string;
  userId: string;
  createdAt: any; // Firestore Timestamp
  symptoms: string[];
  conditions: string[];
  riskLevel: "Low" | "Moderate" | "High";
}

export interface DiseaseInfo {
  id: string;
  name: string;
  category: string;
  overview: string;
  symptoms: string[];
  prevention: string[];
  causes: string[];
  severity: "Low" | "Medium" | "High";
}

export interface EmergencyContact {
  name: string;
  number: string;
  description: string;
}

export interface HospitalInfo {
  name: string;
  address: string;
  distance: string;
  phone: string;
  specialty: string;
}

export interface HealthTip {
  category: "Vaccination" | "Hygiene" | "Nutrition" | "Mental Health" | "Exercise" | "First Aid";
  title: string;
  description: string;
}
