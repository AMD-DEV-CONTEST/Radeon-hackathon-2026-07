import type { Metadata } from "next";

import { LoginView } from "@/features/auth/components/login-view";

export const metadata: Metadata = {
  title: "Sign In — AgentVox",
  description:
    "Sign in to AgentVox to access your AI interview command center.",
};

export default function LoginPage() {
  return <LoginView />;
}
