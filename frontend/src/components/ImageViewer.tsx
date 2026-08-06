import React, { useState } from 'react';
import { Finding, LocalizationMap } from '../types';
import './ImageViewer.css';

interface Props {
  imageUrl: string | null;
  maskB64?: string;
  activeFinding: string | null;
  findings: Finding[];
  localizationMaps?: LocalizationMap[];
}

export default function ImageViewer({
  imageUrl,
  maskB64,
  activeFinding,
  findings,
  localizationMaps = [],
}: Props) {
  const [showEvidence, setShowEvidence] = useState(true);

  if (!imageUrl) {
    return (
      <div className="panel image-viewer empty">
        <h2>X-ray Viewer</h2>
        <p>Upload an image to view it here.</p>
      </div>
    );
  }

  const active = findings.find((f) => f.label === activeFinding);
  const activeMap = localizationMaps.find((m) => m.finding === activeFinding);
  const activeSegmentationMask = activeMap?.segmentation_mask;

  return (
    <div className="panel image-viewer">
      <h2>X-ray Viewer</h2>
      <label className="evidence-toggle">
        <input
          type="checkbox"
          checked={showEvidence}
          onChange={(e) => setShowEvidence(e.target.checked)}
        />
        Show AI evidence
      </label>
      <div className="image-wrap">
        <img src={imageUrl} alt="Chest X-ray" className="xray-image" />
        {showEvidence && activeFinding && activeSegmentationMask ? (
          <img
            src={`data:image/png;base64,${activeSegmentationMask}`}
            alt={`${activeFinding} segmentation evidence`}
            className="mask-overlay active"
            style={{ opacity: 0.8 }}
          />
        ) : (
          showEvidence &&
          maskB64 && (
            <img
              src={`data:image/png;base64,${maskB64}`}
              alt="Combined evidence overlay"
              className="mask-overlay"
              style={{ opacity: 0.55 }}
            />
          )
        )}
        {!activeFinding && active && active.region && (
          <div
            className="bbox-overlay"
            style={{
              left: `${active.region[0]}px`,
              top: `${active.region[1]}px`,
              width: `${active.region[2]}px`,
              height: `${active.region[3]}px`,
            }}
          >
            <span className="bbox-label">{active.label}</span>
          </div>
        )}
      </div>
      <div className="viewer-legend">
        {activeFinding
          ? `Highlighting ${activeFinding} segmentation evidence`
          : 'Evidence: segmentation masks. Hover over report terms to highlight regions.'}
      </div>
    </div>
  );
}
