"use client";

import { Brain, Cpu, Lock, Map, MonitorSmartphone } from "lucide-react";
import { motion } from "framer-motion";

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
</motion.section>;
const features = [
  {
    icon: Brain,
    title: "Knowledge Graph",
    color: "text-cyan-400",
  },
  {
    icon: Cpu,
    title: "Local AI",
    color: "text-purple-400",
  },
  {
    icon: Lock,
    title: "Private",
    color: "text-emerald-400",
  },
  {
    icon: Map,
    title: "Interactive Worlds",
    color: "text-pink-400",
  },
  {
    icon: MonitorSmartphone,
    title: "AMD Radeon",
    color: "text-orange-400",
  },
];

export default function FeatureStrip() {
  return (
    <div className="grid gap-6 md:grid-cols-5">
      {features.map((feature, i) => {
        const Icon = feature.icon;

        return (
          <motion.div
            key={feature.title}
            initial={{ opacity: 0, y: 25 }}
            whileInView={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.08 }}
            viewport={{ once: true }}
            whileHover={{
              y: -8,
              scale: 1.04,
            }}
            className="group rounded-2xl border border-white/10 bg-white/5 p-6 backdrop-blur-xl transition"
          >
            <Icon
              className={`mb-4 h-8 w-8 ${feature.color} transition group-hover:scale-110`}
            />

            <h3 className="font-semibold">{feature.title}</h3>
          </motion.div>
        );
      })}
    </div>
  );
}
