import { NextRequest, NextResponse } from 'next/server';
import Anthropic from '@anthropic-ai/sdk';

export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: 'Missing ANTHROPIC_API_KEY' }, { status: 500 });
  }

  const body = await req.json() as { description: string };
  const { description } = body;
  if (!description?.trim()) {
    return NextResponse.json({ error: 'description is required' }, { status: 400 });
  }

  const client = new Anthropic({ apiKey });

  const system = `You are a professional brand identity designer. Given a user's description of their product/brand, generate a detailed, specific image generation prompt (for DALL-E 3 or Midjourney) that would produce a high-quality app logo / brand avatar.

Rules:
- Output ONLY the prompt text, nothing else. No explanations, no markdown, no quotes.
- The prompt should describe a logo/icon design: style, colors, shapes, mood.
- Keep it under 200 characters if possible.
- Focus on visual elements only (colors, shapes, style, composition).
- Make it suitable for a favicon / app icon (simple, recognizable at small sizes).`;

  try {
    const response = await client.messages.create({
      model: 'claude-sonnet-4-6',
      max_tokens: 256,
      system,
      messages: [{ role: 'user', content: `Brand description: ${description.trim()}` }],
    });

    const promptText = response.content
      .filter((block: any) => block.type === 'text')
      .map((block: any) => block.text)
      .join('\n')
      .trim();

    return NextResponse.json({ prompt: promptText });
  } catch {
    return NextResponse.json({ error: 'Failed to generate prompt' }, { status: 500 });
  }
}
