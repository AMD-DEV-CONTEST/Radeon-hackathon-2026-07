"use client";

import { motion } from "framer-motion";

import { Logo } from "@/components/shared/logo";
import { LoginBrandPanel } from "@/features/auth/components/login-brand-panel";
import { LoginForm } from "@/features/auth/components/login-form";

export function LoginView() {
  return (
    <div className="grid min-h-screen bg-[#050505] lg:grid-cols-[1.15fr_0.85fr]">
      <LoginBrandPanel />

      <motion.section
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, ease: "easeOut", delay: 0.05 }}
        className="flex min-h-screen flex-col bg-[#0F172A] px-5 py-8 sm:px-8 lg:px-10 xl:px-16"
        aria-label="Sign in"
      >
        <div className="mb-8 lg:hidden">
          <Logo />
        </div>

        <div className="flex flex-1 items-center">
          <LoginForm />
        </div>
      </motion.section>
    </div>
  );
}
