"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";

interface Props {
  title: string;
  description: string;
  accent: string;
  emoji: string;
  href: string;
}

export default function WorldCard({
  title,
  description,
  accent,
  emoji,
  href,
}: Props) {
  return (
    <Link href={href} className="block">
      <motion.div
        whileHover={{
          y: -15,
          scale: 1.03,
          rotateX: 6,
          rotateY: -4,
        }}
        whileTap={{ scale: 0.98 }}
        transition={{
          type: "spring",
          stiffness: 180,
        }}
        className="group relative overflow-hidden rounded-3xl border border-white/10 bg-black/40 p-8 backdrop-blur-xl transition-all duration-300 hover:border-[#D5A14C]/40"
      >
        <div
          className={`absolute inset-0 opacity-0 transition duration-500 group-hover:opacity-100 ${accent}`}
        />

        <div className="relative z-10">
          <div className="mb-6 text-5xl">{emoji}</div>

          <h2 className="text-2xl font-bold">{title}</h2>

          <p className="mt-4 leading-7 text-white/60">{description}</p>

          <div className="mt-8 flex items-center gap-2 text-[#D5A14C] transition-all group-hover:gap-4">
            Explore
            <ArrowRight size={18} />
          </div>
        </div>
      </motion.div>
    </Link>
  );
}
