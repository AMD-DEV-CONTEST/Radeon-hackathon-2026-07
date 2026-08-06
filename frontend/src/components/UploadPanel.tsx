import React, { useState } from 'react';
import { AnalysisResponse } from '../types';
import './UploadPanel.css';

interface Props {
  onImageUploaded: (url: string) => void;
  onAnalysisProgress: (patch: Partial<AnalysisResponse>) => void;
  setLoading: (loading: boolean) => void;
}

export default function UploadPanel({ onImageUploaded, onAnalysisProgress, setLoading }: Props) {
  const [file, setFile] = useState<File | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      setFile(selected);
      onImageUploaded(URL.createObjectURL(selected));
    }
  };

  const analyzeFile = async () => {
    if (!file) return;
    setLoading(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch(`/api/analyze-stream?evidence_type=gradcam`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok || !res.body) throw new Error(`Analysis failed (${res.status})`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let report = '';
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === 'analysis') onAnalysisProgress(event.data);
          if (event.type === 'report_token') {
            report += event.token;
            onAnalysisProgress({ report });
          }
          if (event.type === 'complete') onAnalysisProgress(event.data);
        }
        if (done) break;
      }
    } catch (err) {
      alert('Analysis failed. Is the backend running?');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="panel upload-panel">
      <h2>Upload Chest X-ray</h2>
      <input type="file" accept="image/*" onChange={handleFileChange} />
      <button onClick={analyzeFile} disabled={!file}>
        Analyze X-ray
      </button>
    </div>
  );
}
