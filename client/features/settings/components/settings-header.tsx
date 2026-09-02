"use client";

import { motion } from "framer-motion";
import { Settings2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";

export function SettingsHeader() {
  return (
    <motion.header
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="space-y-3"
    >
      <Badge variant="purple" className="gap-1.5">
        <Settings2 className="h-3 w-3" aria-hidden="true" />
        System Configuration
      </Badge>
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
          Command Settings
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
          Manage your account, AI agent behaviors, and technical environment.
        </p>
      </div>
    </motion.header>
  );
}
