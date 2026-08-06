"use client";

import { Cpu } from "lucide-react";
import { motion } from "framer-motion";

export default function RadeonSection() {
  return (
    <section className="rounded-3xl border border-cyan-500/20 bg-[#080808]/70 p-10 backdrop-blur-xl">
      <div className="grid items-center gap-10 md:grid-cols-2">
        <div>
          <h2 className="text-5xl font-bold">Built for AMD Radeon</h2>

          <p className="mt-6 text-lg text-white/70">
            NexusAI performs local inference using ROCm acceleration. No cloud
            APIs. No vendor lock-in. Complete privacy.
          </p>

          <ul className="mt-8 space-y-4 text-white/70">
            <li>✓ Local AI Models</li>

            <li>✓ GPU Accelerated</li>

            <li>✓ Offline First</li>

            <li>✓ Zero Cloud Dependency</li>
          </ul>
        </div>

        <motion.div
          animate={{
            rotate: [0, 6, -6, 0],
          }}
          transition={{
            repeat: Infinity,
            duration: 5,
          }}
          className="flex justify-center"
        >
          <div className="rounded-full bg-gradient-to-r from-purple-600 to-cyan-500 p-10 shadow-[0_0_80px_rgba(0,212,255,.45)]">
            <Cpu size={140} />
          </div>
        </motion.div>
      </div>
      <motion.section
        initial={{
          opacity: 0,
          y: 60,
        }}
        whileInView={{
          opacity: 1,
          y: 0,
        }}
        viewport={{
          once: true,
        }}
        transition={{
          duration: 0.8,
        }}
      >
        ...
      </motion.section>
    </section>
  );
}
