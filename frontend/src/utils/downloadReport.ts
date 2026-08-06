import { jsPDF, GState } from 'jspdf';
import { Finding, LocalizationMap } from '../types';

export interface ChatMessageLike {
  role: 'user' | 'assistant';
  text: string;
}

interface DownloadReportParams {
  imageUrl: string | null;
  report: string;
  findings: Finding[];
  messages: ChatMessageLike[];
  localizationMaps: LocalizationMap[];
}

// Mirrors ChatPanel's own hidden-block markers/logic. Kept as a local copy
// rather than importing from ChatPanel so this utility has no dependency on
// a specific component's internals. If you change the markers in
// ChatPanel.tsx, update them here too.
const HIDE_START = '<think>';
const HIDE_END = '</think>';

function stripHidden(text: string): string {
  let result = text;
  let startIdx = result.indexOf(HIDE_START);
  while (startIdx !== -1) {
    const afterStart = startIdx + HIDE_START.length;
    const endIdx = result.indexOf(HIDE_END, afterStart);
    if (endIdx === -1) {
      result = result.slice(0, startIdx);
      break;
    }
    result = result.slice(0, startIdx) + result.slice(endIdx + HIDE_END.length);
    startIdx = result.indexOf(HIDE_START);
  }
  return result.trimStart();
}

function loadImageElement(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = (err) => reject(err);
    img.src = url;
  });
}

const PAGE_MARGIN = 40;
const LINE_HEIGHT = 16;

/**
 * Tracks the current write position on the page and returns a `write`
 * function that wraps text to the page width and automatically inserts a
 * page break when it would run past the bottom margin.
 */
function createWriter(doc: jsPDF) {
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const maxWidth = pageWidth - PAGE_MARGIN * 2;
  let y = PAGE_MARGIN;

  const ensureSpace = (neededHeight: number) => {
    if (y + neededHeight > pageHeight - PAGE_MARGIN) {
      doc.addPage();
      y = PAGE_MARGIN;
    }
  };

  const writeHeading = (text: string) => {
    ensureSpace(LINE_HEIGHT * 1.5);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(14);
    doc.text(text, PAGE_MARGIN, y);
    y += LINE_HEIGHT * 1.5;
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(11);
  };

  const writeParagraph = (text: string, opts?: { bold?: boolean }) => {
    doc.setFont('helvetica', opts?.bold ? 'bold' : 'normal');
    const lines = doc.splitTextToSize(text, maxWidth) as string[];
    for (const line of lines) {
      ensureSpace(LINE_HEIGHT);
      doc.text(line, PAGE_MARGIN, y);
      y += LINE_HEIGHT;
    }
    doc.setFont('helvetica', 'normal');
  };

  const addSpacing = (amount = LINE_HEIGHT * 0.5) => {
    y += amount;
  };

  const addImageFitted = (img: HTMLImageElement) => {
    const availableWidth = maxWidth;
    const maxImageHeight = pageHeight - PAGE_MARGIN * 2;
    const scale = Math.min(
      availableWidth / img.naturalWidth,
      maxImageHeight / img.naturalHeight,
      1
    );
    const drawWidth = img.naturalWidth * scale;
    const drawHeight = img.naturalHeight * scale;
    ensureSpace(drawHeight);
    doc.addImage(img, 'PNG', PAGE_MARGIN, y, drawWidth, drawHeight);
    y += drawHeight + LINE_HEIGHT * 0.5;
  };

  // Draws a bold title line immediately followed by the base+overlay image,
  // as a single atomic block: the combined height (title + image) is
  // reserved with one ensureSpace() call *before* anything is drawn, so a
  // page break (if needed) happens before the title rather than between the
  // title and the image that follows it.
  const addLabeledOverlayImage = (
    title: string,
    base: HTMLImageElement,
    overlay: HTMLImageElement,
    opacity: number,
    maxImageWidth: number
  ) => {
    const availableWidth = Math.min(maxWidth, maxImageWidth);
    const availableHeight = pageHeight - PAGE_MARGIN * 2 - LINE_HEIGHT;
    const scale = Math.min(
      availableWidth / base.naturalWidth,
      availableHeight / base.naturalHeight,
      1
    );
    const drawWidth = base.naturalWidth * scale;
    const drawHeight = base.naturalHeight * scale;

    ensureSpace(LINE_HEIGHT + drawHeight);

    doc.setFont('helvetica', 'bold');
    doc.text(title, PAGE_MARGIN, y);
    doc.setFont('helvetica', 'normal');
    y += LINE_HEIGHT;

    doc.addImage(base, 'PNG', PAGE_MARGIN, y, drawWidth, drawHeight);
    doc.setGState(new GState({ opacity }));
    doc.addImage(overlay, 'PNG', PAGE_MARGIN, y, drawWidth, drawHeight);
    doc.setGState(new GState({ opacity: 1 }));
    y += drawHeight + LINE_HEIGHT * 0.5;
  };

  return {
    writeHeading,
    writeParagraph,
    addSpacing,
    addImageFitted,
    addLabeledOverlayImage,
    getY: () => y,
  };
}

export async function downloadReportAsPdf({
  imageUrl,
  report,
  findings,
  messages,
  localizationMaps,
}: DownloadReportParams): Promise<void> {
  const doc = new jsPDF({ unit: 'pt', format: 'a4' });
  const writer = createWriter(doc);

  writer.writeHeading('AI Radiology Report');
  writer.writeParagraph(`Generated: ${new Date().toLocaleString()}`);
  writer.addSpacing();

  let baseImg: HTMLImageElement | null = null;
  if (imageUrl) {
    try {
      baseImg = await loadImageElement(imageUrl);
      writer.addImageFitted(baseImg);
    } catch {
      writer.writeParagraph('(Could not load the X-ray image for this report.)');
    }
    writer.addSpacing();
  }

  const visibleFindings = findings.filter(
    (f) => f.confidence > 0.05 && f.label.toLowerCase() !== 'no finding'
  );
  writer.writeHeading('Findings');
  if (visibleFindings.length === 0) {
    writer.writeParagraph('No significant findings above threshold.');
  } else {
    for (const f of visibleFindings) {
      writer.writeParagraph(`${f.label} — ${(f.confidence * 100).toFixed(0)}%`);
    }
  }
  writer.addSpacing();

  // One annotated image per finding that has a localization map, so each
  // potential diagnosis's evidence overlay is shown individually rather
  // than only as a single combined overlay or a text-only list.
  const findingsWithMaps = visibleFindings
    .map((f) => ({ finding: f, map: localizationMaps.find((m) => m.finding === f.label) }))
    .filter((entry) => entry.map?.segmentation_mask);

  if (baseImg && findingsWithMaps.length > 0) {
    writer.writeHeading('Evidence Overlays');
    const pageWidth = doc.internal.pageSize.getWidth();
    const overlayMaxWidth = (pageWidth - PAGE_MARGIN * 2) * 0.6;
    for (const { finding, map } of findingsWithMaps) {
      const title = `${finding.label} — ${(finding.confidence * 100).toFixed(0)}%`;
      try {
        const overlayImg = await loadImageElement(
          `data:image/png;base64,${map!.segmentation_mask}`
        );
        writer.addLabeledOverlayImage(title, baseImg, overlayImg, 0.8, overlayMaxWidth);
      } catch {
        writer.writeParagraph(title, { bold: true });
        writer.writeParagraph('(Could not render evidence overlay for this finding.)');
      }
      writer.addSpacing();
    }
  }

  writer.writeHeading('Report');
  const displayReport = stripHidden(report.replace(/^\s*<think>[\s\S]*?<\/think>\s*/i, ''));
  writer.writeParagraph(displayReport || '(No report generated.)');
  writer.addSpacing();

  writer.writeHeading('Chat Transcript');
  if (messages.length === 0) {
    writer.writeParagraph('No chat messages for this session.');
  } else {
    for (const m of messages) {
      const text = stripHidden(m.text).trim();
      if (!text) continue;
      writer.writeParagraph(`${m.role === 'user' ? 'You' : 'AI'}:`, { bold: true });
      writer.writeParagraph(text);
      writer.addSpacing(LINE_HEIGHT * 0.25);
    }
  }

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  doc.save(`xray-report-${timestamp}.pdf`);
}