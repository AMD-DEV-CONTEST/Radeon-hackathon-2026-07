"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Brain, Castle, Search, Code2 } from "lucide-react";

const worlds = [
  {
    id: "memoryweaver",
    name: "MemoryWeaver",
    description:
      "Explore memories, people, places, and moments as a living timeline.",
    href: "/memoryweaver",
    icon: Brain,
  },
  {
    id: "worldforge",
    name: "WorldForge",
    description:
      "Turn stories and lore into explorable characters, factions, and histories.",
    href: "/worldforge",
    icon: Castle,
  },
  {
    id: "detective",
    name: "Detective",
    description:
      "Explore evidence, timelines, relationships, and source-backed observations.",
    href: "/detective",
    icon: Search,
  },
  {
    id: "codeverse",
    name: "CodeVerse",
    description:
      "Transform software architecture into an interactive visual world.",
    href: "/codeverse",
    icon: Code2,
  },
];

export function WorldSelector() {
  return (
    <section className="mx-auto grid w-full max-w-6xl gap-4 md:grid-cols-2">
      {worlds.map((world, index) => {
        const Icon = world.icon;

        return (
          <motion.div
            key={world.id}
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.12 * index, duration: 0.45 }}
          >
            <Link
              href={world.href}
              className="group block min-h-56 rounded-3xl border border-white/10 bg-white/[0.035] p-7 backdrop-blur transition hover:-translate-y-1 hover:border-cyan-300/30 hover:bg-white/[0.055]"
            >
              <div className="mb-10 flex items-center justify-between">
                <Icon className="h-7 w-7 text-cyan-200" />
                <span className="text-xs uppercase tracking-[0.22em] text-white/35">
                  Enter World
                </span>
              </div>
              <h2 className="text-2xl font-medium tracking-tight">
                {world.name}
              </h2>
              <p className="mt-3 max-w-md leading-7 text-white/55">
                {world.description}
              </p>
            </Link>
          </motion.div>
        );
      })}
    </section>
  );
}
