"use client";

import WorldCard from "./WorldCard";

const worlds = [
  {
    title: "MemoryWeaver",
    href: "/memoryweaver",
    emoji: "🧠",
    accent: "bg-gradient-to-br from-purple-600/20 to-transparent",
    description:
      "Transform conversations and experiences into searchable memory timelines.",
  },
  {
    title: "WorldForge",
    href: "/worldforge",
    emoji: "🌍",
    accent: "bg-gradient-to-br from-cyan-500/20 to-transparent",
    description:
      "Generate interactive semantic worlds from stories, documents and knowledge.",
  },
  {
    title: "Detective",
    href: "/detective",
    emoji: "🕵️",
    accent: "bg-gradient-to-br from-pink-500/20 to-transparent",
    description:
      "Investigate evidence with relationship graphs and AI-assisted reasoning.",
  },
  {
    title: "CodeVerse",
    href: "/codeverse",
    emoji: "💻",
    accent: "bg-gradient-to-br from-emerald-500/20 to-transparent",
    description:
      "Navigate repositories as connected software worlds with dependency intelligence.",
  },
];

export default function WorldGrid() {
  return (
    <>
      <h2 className="mb-12 text-center text-5xl font-bold">
        Interactive Worlds
      </h2>

      <div className="grid gap-8 md:grid-cols-2">
        {worlds.map((world) => (
          <WorldCard key={world.title} {...world} />
        ))}
      </div>
    </>
  );
}
