export type SettingsSection =
  | "profile"
  | "account"
  | "notifications"
  | "appearance"
  | "interview"
  | "ai"
  | "apiKeys"
  | "security"
  | "devices"
  | "danger";

export type ThemeMode = "dark" | "light" | "system";
export type AccentColor = "purple" | "blue" | "cyan" | "rose";
export type FontSize = "sm" | "md" | "lg";
export type Difficulty = "easy" | "medium" | "hard" | "adaptive";
export type AiPersonality = "coach" | "strict" | "neutral" | "friendly";
export type ResponseStyle = "concise" | "balanced" | "detailed";
export type AiModel = "vox-1" | "vox-1-pro" | "vox-lite";

export interface UserProfileSettings {
  fullName: string;
  email: string;
  phone: string;
  jobTitle: string;
  preferredRole: string;
  experience: string;
  timezone: string;
  avatarInitials: string;
}

export interface InterviewPreferenceSettings {
  preferredDifficulty: Difficulty;
  interviewDurationMinutes: number;
  questionCount: number;
  voiceSpeed: number;
  aiPersonality: AiPersonality;
}

export interface NotificationSettings {
  email: boolean;
  push: boolean;
  interviewReminder: boolean;
  weeklySummary: boolean;
}

export interface AppearanceSettings {
  theme: ThemeMode;
  accentColor: AccentColor;
  fontSize: FontSize;
}

export interface SecuritySettings {
  twoFactorEnabled: boolean;
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
}

export interface ActiveSession {
  id: string;
  device: string;
  location: string;
  ipAddress: string;
  isCurrent: boolean;
  lastActive: string;
}

export interface DeviceOption {
  id: string;
  label: string;
  kind: "microphone" | "camera" | "speaker";
}

export interface DeviceSettings {
  microphoneId: string;
  cameraId: string;
  speakerId: string;
  devices: ReadonlyArray<DeviceOption>;
}

export interface AiSettings {
  preferredModel: AiModel;
  creativity: number;
  temperature: number;
  responseStyle: ResponseStyle;
}

export interface ApiKeySettings {
  openaiKey: string;
  amdKey: string;
  deepgramKey: string;
}

export interface StorageUsage {
  usedGb: number;
  totalGb: number;
  percent: number;
}

export interface UserSettings {
  profile: UserProfileSettings;
  interview: InterviewPreferenceSettings;
  notifications: NotificationSettings;
  appearance: AppearanceSettings;
  security: Pick<SecuritySettings, "twoFactorEnabled">;
  sessions: ReadonlyArray<ActiveSession>;
  devices: DeviceSettings;
  ai: AiSettings;
  apiKeys: ApiKeySettings;
  storage: StorageUsage;
  updatedAt: string;
}

export interface UpdateSettingsPayload {
  profile?: Partial<UserProfileSettings>;
  interview?: Partial<InterviewPreferenceSettings>;
  notifications?: Partial<NotificationSettings>;
  appearance?: Partial<AppearanceSettings>;
  security?: Partial<Pick<SecuritySettings, "twoFactorEnabled">>;
  devices?: Partial<Omit<DeviceSettings, "devices">>;
  ai?: Partial<AiSettings>;
  apiKeys?: Partial<ApiKeySettings>;
}
