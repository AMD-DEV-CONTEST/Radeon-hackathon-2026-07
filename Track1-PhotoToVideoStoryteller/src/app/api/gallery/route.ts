import { NextRequest, NextResponse } from "next/server";
import { db } from "@/db";
import { generations } from "@/db/schema";
import { eq, desc } from "drizzle-orm";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = parseInt(searchParams.get("limit") || "50");
    const offset = parseInt(searchParams.get("offset") || "0");
    const style = searchParams.get("style");
    const search = searchParams.get("search");

    let query = db.select().from(generations).orderBy(desc(generations.createdAt)).limit(limit).offset(offset);

    const results = await query;

    let filtered = results;

    if (style && style !== "all") {
      filtered = filtered.filter((g) => g.style === style);
    }

    if (search) {
      const searchLower = search.toLowerCase();
      filtered = filtered.filter(
        (g) =>
          g.prompt.toLowerCase().includes(searchLower) ||
          (g.negativePrompt && g.negativePrompt.toLowerCase().includes(searchLower))
      );
    }

    return NextResponse.json({
      images: filtered,
      total: results.length,
      limit,
      offset,
    });
  } catch (error) {
    console.error("Error fetching gallery:", error);
    return NextResponse.json(
      { error: "Failed to fetch gallery" },
      { status: 500 }
    );
  }
}

export async function DELETE(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const id = searchParams.get("id");

    if (!id) {
      return NextResponse.json(
        { error: "ID is required" },
        { status: 400 }
      );
    }

    await db.delete(generations).where(eq(generations.id, parseInt(id)));

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Error deleting generation:", error);
    return NextResponse.json(
      { error: "Failed to delete generation" },
      { status: 500 }
    );
  }
}
