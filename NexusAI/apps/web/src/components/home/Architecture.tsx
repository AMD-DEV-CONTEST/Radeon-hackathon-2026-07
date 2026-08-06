"use client";

import { motion } from "framer-motion";

const layers = [
  "Frontend",
  "Knowledge Engine",
  "MemoryWeaver",
  "WorldForge",
  "Detective",
  "CodeVerse",
  "Local AI Models",
  "AMD Radeon GPU",
];

export default function Architecture() {
  return (
    <section>
      <h2 className="mb-16 text-center text-5xl font-bold">
        System Architecture
      </h2>

      <div className="mx-auto flex max-w-xl flex-col items-center">
        {layers.map((layer, index) => (
          <div key={layer} className="flex flex-col items-center">
            <motion.div
              initial={{ opacity: 0, y: 40 }}
              whileInView={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.1 }}
              viewport={{ once: true }}
              className="w-80 rounded-2xl border border-white/10 bg-[#080808]/70 p-5 text-center backdrop-blur-xl"
            >
              {layer}
            </motion.div>

            {index !== layers.length - 1 && (
              <motion.div
                animate={{ opacity: [0.2, 1, 0.2] }}
                transition={{
                  repeat: Infinity,
                  duration: 2,
                }}
                className="h-10 w-[2px] bg-cyan-400"
              />
            )}
          </div>
        ))}
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
