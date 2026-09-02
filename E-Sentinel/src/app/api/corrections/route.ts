/**
 * POST /api/corrections — Record human correction of AI prediction.
 * Used by the "纠正AI" button on Feishu cards and the web dashboard.
 */
import { NextResponse } from "next/server";
import { recordCorrection } from "@/lib/few-shot";

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => null);
    if (!body) {
      return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
    }

    const conversation = typeof body.conversation === "string" ? body.conversation.trim() : "";
    if (!conversation) {
      return NextResponse.json({ error: "conversation is required" }, { status: 400 });
    }

    const aiPrediction = typeof body.ai_prediction === "object" ? body.ai_prediction : {};
    const humanCorrection = typeof body.human_correction === "object" ? body.human_correction : {};
    const correctionType = typeof body.correction_type === "string" ? body.correction_type : "risk_level";
    const sessionId = typeof body.session_id === "string" ? body.session_id : undefined;

    const result = await recordCorrection({
      session_id: sessionId,
      conversation,
      ai_prediction: aiPrediction as Record<string, unknown>,
      human_correction: humanCorrection as Record<string, unknown>,
      correction_type: correctionType,
    });

    if (!result.success) {
      return NextResponse.json({ error: result.error }, { status: 500 });
    }

    return NextResponse.json({ success: true, id: result.id });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "internal_error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
