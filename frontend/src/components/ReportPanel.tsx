import React, { useState } from 'react';
import { Finding, LocalizationMap } from '../types';
import { downloadReportAsPdf, ChatMessageLike } from '../utils/downloadReport';
import './ReportPanel.css';

interface Props {
  report: string;
  reportSource?: 'llm' | 'template';
  findings: Finding[];
  confidenceScores?: Record<string, number>;
  onHoverTerm: (term: string) => void;
  onLeaveTerm: () => void;
  imageUrl: string | null;
  chatMessages: ChatMessageLike[];
  chatLoading: boolean;
  localizationMaps: LocalizationMap[];
}

export default function ReportPanel({
  report,
  reportSource,
  findings,
  confidenceScores = {},
  onHoverTerm,
  onLeaveTerm,
  imageUrl,
  chatMessages,
  chatLoading,
  localizationMaps,
}: Props) {
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      await downloadReportAsPdf({
        imageUrl,
        report,
        findings,
        messages: chatMessages,
        localizationMaps,
      });
    } catch (err) {
      console.error('[report] Failed to generate PDF:', err);
    } finally {
      setDownloading(false);
    }
  };
  const visibleFindings = findings.filter(
    (f) => f.confidence > 0.05 && f.label.toLowerCase() !== 'no finding'
  );
  const labels = visibleFindings.map((f) => f.label.toLowerCase());

  const renderWord = (word: string, idx: number, words: string[]) => {
    const normalizedWords = words.map((value) =>
      value.replace(/[^a-zA-Z0-9 ]/g, '').toLowerCase()
    );
    const matched = findings.find((f) => {
      const labelWords = f.label
        .replace(/[^a-zA-Z0-9 ]/g, '')
        .toLowerCase()
        .split(' ')
        .filter(Boolean);
      return labelWords.some((_, offset) =>
        labelWords.every(
          (labelWord, labelIndex) =>
            normalizedWords[idx - offset + labelIndex] === labelWord
        )
      );
    });
    if (matched) {
      return (
        <span
          key={idx}
          className="highlight-term"
          onMouseEnter={() => onHoverTerm(matched.label)}
          onMouseLeave={onLeaveTerm}
          title={`Confidence: ${(matched.confidence * 100).toFixed(0)}%`}
        >
          {word}
        </span>
      );
    }
    return <span key={idx}>{word} </span>;
  };

  // Native Jinja chat templates may prepend an empty <think> block even when
  // thinking is disabled. Keep the original report for the API/chat context,
  // but hide that transport artifact in the rendered report.
  const displayReport = report.replace(/^\s*<think>[\s\S]*?<\/think>\s*/i, '');
  const lines = displayReport.split('\n');

  return (
    <div className="panel report-panel">
      <div className="report-panel-header">
        <h2>AI Radiology Report</h2>
        <button
          className="download-report-btn"
          onClick={handleDownload}
          disabled={downloading || !report || chatLoading}
          title={
            chatLoading
              ? 'Wait for the current answer to finish before downloading'
              : 'Download this report, including findings and the full chat, as a PDF'
          }
        >
          {downloading ? 'Preparing…' : chatLoading ? 'AI is answering…' : 'Download Report'}
        </button>
      </div>
      {report && (
        <div className="report-source">
          {reportSource === 'llm' ? 'LLM-generated report' : 'Template fallback report'}
        </div>
      )}
      <div className="evidence-badge">Evidence: Grad-CAM</div>
      <div className="findings-list">
        <strong>Detected findings:</strong>
        <ul>
          {visibleFindings.map((f) => (
            <li key={f.label} className="finding-item">
                <span
                  className="finding-label"
                  onMouseEnter={() => onHoverTerm(f.label)}
                  onMouseLeave={onLeaveTerm}
                >
                  {f.label}
                </span>
                <span className="confidence-value">{(f.confidence * 100).toFixed(0)}%</span>
                <div className="confidence-bar">
                  <div
                    className="confidence-fill"
                    style={{ width: `${f.confidence * 100}%` }}
                  />
                </div>
              </li>
            ))}
        </ul>
      </div>
      <div className="report-text">
        {lines.map((line, i) => (
          <p key={i}>
            {line.split(/\s+/).map((word, j, words) => renderWord(word + ' ', j, words))}
          </p>
        ))}
      </div>
      <p className="disclaimer">
        <em>For research and demonstration only. Not a medical diagnosis.</em>
      </p>
    </div>
  );
}