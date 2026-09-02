import { z } from "zod";

export const profileSettingsSchema = z.object({
  fullName: z.string().min(2, "Full name is required"),
  email: z.string().email("Enter a valid email"),
  phone: z.string().min(7, "Enter a valid phone number"),
  jobTitle: z.string().min(2, "Job title is required"),
  preferredRole: z.string().min(2, "Preferred role is required"),
  experience: z.string().min(1, "Experience is required"),
  timezone: z.string().min(2, "Timezone is required"),
});

export const interviewSettingsSchema = z.object({
  preferredDifficulty: z.enum(["easy", "medium", "hard", "adaptive"]),
  interviewDurationMinutes: z.number().min(15).max(120),
  questionCount: z.number().min(4).max(30),
  voiceSpeed: z.number().min(0.5).max(2),
  aiPersonality: z.enum(["coach", "strict", "neutral", "friendly"]),
});

export const notificationSettingsSchema = z.object({
  email: z.boolean(),
  push: z.boolean(),
  interviewReminder: z.boolean(),
  weeklySummary: z.boolean(),
});

export const appearanceSettingsSchema = z.object({
  theme: z.enum(["dark", "light", "system"]),
  accentColor: z.enum(["purple", "blue", "cyan", "rose"]),
  fontSize: z.enum(["sm", "md", "lg"]),
});

export const securitySettingsSchema = z
  .object({
    twoFactorEnabled: z.boolean(),
    currentPassword: z.string(),
    newPassword: z.string(),
    confirmPassword: z.string(),
  })
  .superRefine((values, ctx) => {
    const changingPassword =
      values.currentPassword.length > 0 ||
      values.newPassword.length > 0 ||
      values.confirmPassword.length > 0;

    if (!changingPassword) {
      return;
    }

    if (values.currentPassword.length < 8) {
      ctx.addIssue({
        code: "custom",
        path: ["currentPassword"],
        message: "Current password is required",
      });
    }

    if (values.newPassword.length < 8) {
      ctx.addIssue({
        code: "custom",
        path: ["newPassword"],
        message: "New password must be at least 8 characters",
      });
    }

    if (values.newPassword !== values.confirmPassword) {
      ctx.addIssue({
        code: "custom",
        path: ["confirmPassword"],
        message: "Passwords do not match",
      });
    }
  });

export const deviceSettingsSchema = z.object({
  microphoneId: z.string().min(1, "Select a microphone"),
  cameraId: z.string().min(1, "Select a camera"),
  speakerId: z.string().min(1, "Select a speaker"),
});

export const aiSettingsSchema = z.object({
  preferredModel: z.enum(["vox-1", "vox-1-pro", "vox-lite"]),
  creativity: z.number().min(0).max(100),
  temperature: z.number().min(0).max(2),
  responseStyle: z.enum(["concise", "balanced", "detailed"]),
});

export const apiKeySettingsSchema = z.object({
  openaiKey: z.string().min(1, "OpenAI key is required"),
  amdKey: z.string().min(1, "AMD API key is required"),
  deepgramKey: z.string().min(1, "Deepgram key is required"),
});

export type ProfileSettingsFormValues = z.infer<typeof profileSettingsSchema>;
export type InterviewSettingsFormValues = z.infer<typeof interviewSettingsSchema>;
export type NotificationSettingsFormValues = z.infer<
  typeof notificationSettingsSchema
>;
export type AppearanceSettingsFormValues = z.infer<
  typeof appearanceSettingsSchema
>;
export type SecuritySettingsFormValues = z.infer<typeof securitySettingsSchema>;
export type DeviceSettingsFormValues = z.infer<typeof deviceSettingsSchema>;
export type AiSettingsFormValues = z.infer<typeof aiSettingsSchema>;
export type ApiKeySettingsFormValues = z.infer<typeof apiKeySettingsSchema>;
