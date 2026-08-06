import React, { useState } from 'react';
import './App.css';
import UploadPanel from './components/UploadPanel';
import ImageViewer from './components/ImageViewer';
import ReportPanel from './components/ReportPanel';
import ChatPanel from './components/ChatPanel';
import { AnalysisResponse, Finding } from './types';

function App() {
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [activeFinding, setActiveFinding] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<{ role: 'user' | 'assistant'; text: string }[]>([]);
  const [chatLoading, setChatLoading] = useState(false);

  const onImageUploaded = (url: string) => {
    setImageUrl(url);
    setResult(null);
    setActiveFinding(null);
  };

  const onAnalysisProgress = (patch: Partial<AnalysisResponse>) => {
    setResult((previous) => ({ ...(previous || {}), ...patch }) as AnalysisResponse);
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>RiBEye - Explainable AI Radiology Assistant</h1>
        <p>Upload a chest X-ray to get an AI-generated, explainable radiology report.</p>
      </header>

      <main className="app-main">
        <section className="left-column">
          <UploadPanel
            onImageUploaded={onImageUploaded}
            onAnalysisProgress={onAnalysisProgress}
            setLoading={setLoading}
          />
          <ImageViewer
            imageUrl={imageUrl}
            maskB64={result?.mask_b64}
            activeFinding={activeFinding}
            findings={result?.findings || []}
            localizationMaps={result?.localization_maps || []}
          />
          {loading && <div className="spinner">Analyzing X-ray...</div>}
        </section>

        <section className="right-column">
          <ReportPanel
            report={result?.report || ''}
            reportSource={result?.report_source}
            findings={result?.findings || []}
            confidenceScores={result?.confidence_scores || {}}
            onHoverTerm={setActiveFinding}
            onLeaveTerm={() => setActiveFinding(null)}
            imageUrl={imageUrl}
            chatMessages={chatMessages}
            chatLoading={chatLoading}
            localizationMaps={result?.localization_maps || []}
          />
          <ChatPanel
            key={result?.image_id || imageUrl || 'no-image'}
            report={result?.report || ''}
            findings={result?.findings || []}
            chatSeed={result?.chat_seed || []}
            onMessagesChange={setChatMessages}
            onLoadingChange={setChatLoading}
          />
        </section>
      </main>
    </div>
  );
}

export default App;