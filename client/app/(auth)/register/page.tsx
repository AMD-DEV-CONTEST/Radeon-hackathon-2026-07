import type { Metadata } from "next";

import { RegisterView } from "@/features/auth/components/register-view";

export const metadata: Metadata = {
  title: "Create Account — AgentVox",
  description:
    "Register for AgentVox to access multi-agent AI interviewing and analytics.",
};

export default function RegisterPage() {
  return <RegisterView />;
}
