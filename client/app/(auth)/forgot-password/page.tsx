import type { Metadata } from "next";

import { ForgotPasswordView } from "@/features/auth/components/forgot-password-view";

export const metadata: Metadata = {
  title: "Forgot Password — AgentVox",
  description:
    "Reset your AgentVox password with a secure email verification link.",
};

export default function ForgotPasswordPage() {
  return <ForgotPasswordView />;
}
