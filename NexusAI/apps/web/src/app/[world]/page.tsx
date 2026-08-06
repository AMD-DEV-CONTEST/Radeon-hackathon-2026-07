import Link from "next/link";
import WorldForgeScene from "@/components/worldforge/WorldForgeScene";
import MemoryCanvas from "@/components/memoryweaver/MemoryCanvas";
import DetectiveCanvas from "@/components/detective/DetectiveCanvas";
import CodeVerseCanvas from "@/components/codeverse/CodeVerseCanvas";

const worldNames: Record<string, string> = {
  memoryweaver: "MemoryWeaver",
  worldforge: "WorldForge",
  detective: "Detective",
  codeverse: "CodeVerse",
};

export default async function WorldPage({
  params,
}: {
  params: Promise<{ world: string }>;
}) {
  const { world } = await params;
  const name = worldNames[world] ?? "Unknown World";

  if (world === "codeverse") {
    return (
      <main className="min-h-screen px-6 py-10">
        <div className="mx-auto max-w-7xl">
          <CodeVerseCanvas />
        </div>
      </main>
    );
  }
  if (world === "detective") {
    return (
      <main className="min-h-screen px-6 py-10">
        <div className="mx-auto max-w-7xl">
          <DetectiveCanvas />
        </div>
      </main>
    );
  }
  if (world === "memoryweaver") {
    return (
      <main className="min-h-screen px-6 py-10">
        <div className="mx-auto max-w-7xl">
          <p className="text-xs uppercase tracking-[0.3em] text-cyan-200/70">
            NexusAI • MemoryWeaver
          </p>

          <h1 className="mt-4 text-5xl font-medium tracking-tight">
            Explore your memories.
          </h1>

          <p className="mt-5 mb-8 max-w-2xl leading-7 text-white/55">
            Browse memories, people, places and experiences through an
            interactive timeline.
          </p>

          <MemoryCanvas />
        </div>
      </main>
    );
  } // WorldForge gets its dedicated interactive 3D experience
  if (world === "worldforge") {
    return (
      <main className="min-h-screen px-6 py-10">
        <div className="mx-auto max-w-7xl">
          <div className="mb-8">
            <p className="text-xs uppercase tracking-[0.3em] text-cyan-200/70">
              NexusAI · WorldForge
            </p>

            <h1 className="mt-4 text-5xl font-medium tracking-tight">
              Knowledge becomes a world.
            </h1>

            <p className="mt-5 max-w-2xl leading-7 text-white/55">
              Explore structured knowledge as an interactive 3D environment.
              WorldForge transforms entities, places, organizations, and
              relationships into a living digital world.
            </p>
          </div>

          <WorldForgeScene />

          <div className="mt-6 flex items-center justify-between">
            <div className="flex gap-3 text-xs text-white/40">
              <span className="rounded-full border border-white/10 px-3 py-1.5">
                Drag · Rotate
              </span>

              <span className="rounded-full border border-white/10 px-3 py-1.5">
                Scroll · Zoom
              </span>

              <span className="rounded-full border border-cyan-400/20 px-3 py-1.5 text-cyan-200">
                WorldForge v0.9.1
              </span>
            </div>

            <Link
              href="/"
              className="text-sm text-cyan-200 hover:text-cyan-100"
            >
              ← Return to Nexus
            </Link>
          </div>
        </div>
      </main>
    );
  }

  // Existing gateway for the other NexusAI worlds
  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-3xl rounded-3xl border border-white/10 bg-white/[0.035] p-10">
        <p className="text-xs uppercase tracking-[0.3em] text-cyan-200/70">
          Nexus World
        </p>

        <h1 className="mt-4 text-5xl font-medium tracking-tight">{name}</h1>

        <p className="mt-5 leading-7 text-white/55">
          The gateway is online. Domain intelligence and visual exploration
          arrive in the next milestones.
        </p>

        <Link
          href="/"
          className="mt-10 inline-block text-sm text-cyan-200 hover:text-cyan-100"
        >
          ← Return to Nexus
        </Link>
      </div>
    </main>
  );
}
