/** Simple character-window chunker with overlap (Chinese-friendly). */

export type TextChunk = {
  index: number;
  content: string;
  tokenEstimate: number;
};

export function chunkText(
  text: string,
  options?: { maxChars?: number; overlapChars?: number }
): TextChunk[] {
  const maxChars = options?.maxChars ?? 420;
  const overlapChars = options?.overlapChars ?? 60;
  const cleaned = text.replace(/\r\n/g, "\n").trim();
  if (!cleaned) return [];

  // Prefer splitting on blank lines / headings when possible.
  const paragraphs = cleaned.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  const blocks: string[] = [];
  let current = "";
  for (const para of paragraphs) {
    if ((current + "\n\n" + para).length <= maxChars) {
      current = current ? `${current}\n\n${para}` : para;
      continue;
    }
    if (current) blocks.push(current);
    if (para.length <= maxChars) {
      current = para;
    } else {
      // hard-split long paragraph
      for (let i = 0; i < para.length; i += maxChars - overlapChars) {
        blocks.push(para.slice(i, i + maxChars));
      }
      current = "";
    }
  }
  if (current) blocks.push(current);

  // Second pass: merge tiny trailing blocks and enforce overlap windows
  const chunks: TextChunk[] = [];
  for (let i = 0; i < blocks.length; i++) {
    const content = blocks[i]!;
    chunks.push({
      index: chunks.length,
      content,
      tokenEstimate: Math.ceil(content.length / 2)
    });
  }
  return chunks;
}
