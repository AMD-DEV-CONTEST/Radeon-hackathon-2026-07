import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { generations } from "@/db/schema";
import { eq } from "drizzle-orm";
import { generateSeed } from "@/lib/constants";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const id = searchParams.get("id");

    if (id) {
      const result = await db
        .select()
        .from(generations)
        .where(eq(generations.id, parseInt(id)))
        .limit(1);
      return NextResponse.json(result[0] || null);
    }

    const all = await db.select().from(generations).orderBy(generations.createdAt);
    return NextResponse.json(all);
  } catch (error) {
    console.error("Error fetching generations:", error);
    return NextResponse.json(
      { error: "Failed to fetch generations" },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const {
      prompt,
      negativePrompt,
      mode = "text-to-image",
      style = "realistic",
      width = 1024,
      height = 1024,
      steps = 30,
      seed,
    } = body;

    if (!prompt || typeof prompt !== "string" || prompt.trim().length === 0) {
      return NextResponse.json(
        { error: "Prompt is required" },
        { status: 400 }
      );
    }

    // Simulate generation time based on mode and steps
    const baseTime = mode === "text-to-image" ? 2000 : 3000;
    const stepMultiplier = steps / 30;
    const generationTime = Math.round(baseTime * stepMultiplier);

    // Simulate the generation with a delay
    await new Promise((resolve) => setTimeout(resolve, Math.min(generationTime, 500)));

    // Generate a deterministic "image" based on the prompt and seed
    const actualSeed = seed || generateSeed();
    const promptHash = hashCode(prompt + actualSeed);
    const imageUrl = generateSimulatedImageUrl(prompt, actualSeed, style);

    const newGeneration = {
      prompt: prompt.trim(),
      negativePrompt: negativePrompt?.trim() || null,
      mode,
      style,
      imageUrl,
      thumbnailUrl: imageUrl, // In production, generate a separate thumbnail
      width,
      height,
      seed: actualSeed,
      steps,
      isPublic: true,
    };

    const result = await db.insert(generations).values(newGeneration).returning();

    return NextResponse.json({
      ...result[0],
      generationTime,
    });
  } catch (error) {
    console.error("Error creating generation:", error);
    return NextResponse.json(
      { error: "Failed to create generation" },
      { status: 500 }
    );
  }
}

function hashCode(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash;
  }
  return Math.abs(hash);
}

function generateSimulatedImageUrl(prompt: string, seed: number, style: string): string {
  // Create a visual representation using SVG with gradients and shapes
  const colors = getStyleColors(style);
  const hash = hashCode(prompt + seed);

  // Generate deterministic random positions based on hash
  const rng = seededRandom(hash);
  const shapes = Array.from({ length: 15 }, () => ({
    type: ["circle", "rect", "path"][Math.floor(rng() * 3)] as string,
    x: rng() * 100,
    y: rng() * 100,
    size: 10 + rng() * 40,
    color: colors[Math.floor(rng() * colors.length)],
    opacity: 0.2 + rng() * 0.4,
    rotation: rng() * 360,
  }));

  const svgContent = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
      <defs>
        <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color:${colors[0]};stop-opacity:1" />
          <stop offset="50%" style="stop-color:${colors[1]};stop-opacity:1" />
          <stop offset="100%" style="stop-color:${colors[2]};stop-opacity:1" />
        </linearGradient>
        <filter id="glow">
          <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
          <feMerge>
            <feMergeNode in="coloredBlur"/>
            <feMergeNode in="SourceGraphic"/>
          </feMerge>
        </filter>
      </defs>
      <rect width="1024" height="1024" fill="url(#bg)"/>
      ${shapes.map(s => {
        if (s.type === "circle") {
          return `<circle cx="${s.x * 10.24}" cy="${s.y * 10.24}" r="${s.size}" fill="${s.color}" opacity="${s.opacity}" filter="url(#glow)"/>`;
        } else if (s.type === "rect") {
          return `<rect x="${(s.x * 10.24) - (s.size/2)}" y="${(s.y * 10.24) - (s.size/2)}" width="${s.size}" height="${s.size}" fill="${s.color}" opacity="${s.opacity}" transform="rotate(${s.rotation} ${(s.x * 10.24)}, ${(s.y * 10.24)})" filter="url(#glow)"/>`;
        } else {
          return `<path d="M${s.x * 10.24},${s.y * 10.24 - s.size} Q${s.x * 10.24 + s.size},${s.y * 10.24} ${s.x * 10.24},${s.y * 10.24 + s.size} Q${s.x * 10.24 - s.size},${s.y * 10.24} ${s.x * 10.24},${s.y * 10.24 - s.size}" fill="${s.color}" opacity="${s.opacity}" filter="url(#glow)"/>`;
        }
      }).join("\n      ")}
      <text x="512" y="950" font-family="system-ui, sans-serif" font-size="24" fill="white" text-anchor="middle" opacity="0.7">
        NeuralForge AI • ${style}
      </text>
    </svg>
  `;

  const base64 = Buffer.from(svgContent).toString("base64");
  return `data:image/svg+xml;base64,${base64}`;
}

function getStyleColors(style: string): string[] {
  const palettes: Record<string, string[]> = {
    realistic: ["#1a1a2e", "#16213e", "#0f3460"],
    anime: ["#ff6b6b", "#ffd93d", "#6bcb77"],
    "digital-art": ["#6366f1", "#8b5cf6", "#a855f7"],
    "oil-painting": ["#8b4513", "#a0522d", "#cd853f"],
    watercolor: ["#e6e6fa", "#b0c4de", "#d8bfd8"],
    cyberpunk: ["#ff00ff", "#00ffff", "#ff0000"],
    fantasy: ["#4a0e4e", "#8b5cf6", "#c084fc"],
    minimalist: ["#f5f5f5", "#e0e0e0", "#bdbdbd"],
    vintage: ["#d4a574", "#c4956a", "#b8855a"],
    abstract: ["#ff6b6b", "#4ecdc4", "#45b7d1"],
    "3d-render": ["#2d3436", "#636e72", "#b2bec3"],
    sketch: ["#2c3e50", "#34495e", "#7f8c8d"],
  };
  return palettes[style] || palettes.realistic;
}

function seededRandom(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}
