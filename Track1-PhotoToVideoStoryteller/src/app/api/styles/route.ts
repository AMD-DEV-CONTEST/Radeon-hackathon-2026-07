import { NextResponse } from "next/server";
import { AI_STYLES } from "@/lib/constants";

export async function GET() {
  try {
    return NextResponse.json({
      styles: AI_STYLES.map((s) => ({
        id: s.id,
        name: s.name,
        description: s.description,
        category: s.category,
      })),
    });
  } catch (error) {
    console.error("Error fetching styles:", error);
    return NextResponse.json(
      { error: "Failed to fetch styles" },
      { status: 500 }
    );
  }
}
