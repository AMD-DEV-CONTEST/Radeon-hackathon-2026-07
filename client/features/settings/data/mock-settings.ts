import type { UserSettings } from "@/features/settings/types/settings.types";

export async function simulateNetworkLatency(
  ms: number = 360
): Promise<void> {
  await new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export const MOCK_USER_SETTINGS: UserSettings = {
  profile: {
    fullName: "Sarah Jenkins",
    email: "s.jenkins@agentvox.ai",
    phone: "+1 (415) 555-0142",
    jobTitle: "Sr. HR Operations Lead",
    preferredRole: "Hiring Operations Lead",
    experience: "8+ years",
    timezone: "Pacific Standard Time (UTC-8)",
    avatarInitials: "SJ",
  },
  interview: {
    preferredDifficulty: "adaptive",
    interviewDurationMinutes: 60,
    questionCount: 12,
    voiceSpeed: 1,
    aiPersonality: "coach",
  },
  notifications: {
    email: true,
    push: true,
    interviewReminder: true,
    weeklySummary: false,
  },
  appearance: {
    theme: "dark",
    accentColor: "purple",
    fontSize: "md",
  },
  security: {
    twoFactorEnabled: true,
  },
  sessions: [
    {
      id: "sess-1",
      device: "macOS Monterey • Chrome 118",
      location: "San Francisco, USA",
      ipAddress: "192.168.1.1",
      isCurrent: true,
      lastActive: "Just now",
    },
    {
      id: "sess-2",
      device: "iOS 17 • Safari",
      location: "San Francisco, USA",
      ipAddress: "192.168.1.24",
      isCurrent: false,
      lastActive: "2d ago",
    },
  ],
  devices: {
    microphoneId: "mic-default",
    cameraId: "cam-default",
    speakerId: "spk-default",
    devices: [
      {
        id: "mic-default",
        label: "MacBook Pro Microphone",
        kind: "microphone",
      },
      {
        id: "mic-usb",
        label: "Shure MV7",
        kind: "microphone",
      },
      {
        id: "cam-default",
        label: "FaceTime HD Camera",
        kind: "camera",
      },
      {
        id: "cam-logi",
        label: "Logitech Brio",
        kind: "camera",
      },
      {
        id: "spk-default",
        label: "MacBook Pro Speakers",
        kind: "speaker",
      },
      {
        id: "spk-airpods",
        label: "AirPods Pro",
        kind: "speaker",
      },
    ],
  },
  ai: {
    preferredModel: "vox-1-pro",
    creativity: 62,
    temperature: 0.7,
    responseStyle: "balanced",
  },
  apiKeys: {
    openaiKey: "sk-live-••••••••••••9f2a",
    amdKey: "amd-••••••••••••7c11",
    deepgramKey: "dg-••••••••••••4b90",
  },
  storage: {
    usedGb: 12.4,
    totalGb: 20,
    percent: 64,
  },
  updatedAt: "2026-08-06T07:40:00.000Z",
};
