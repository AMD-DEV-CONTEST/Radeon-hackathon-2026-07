import { FileOutput } from "lucide-react";

import type { ReviewRegion } from "../../lib/types";
import { titleCase } from "../../lib/utils";

interface PdfPreviewProps {
  previewUrls: string[];
  regions: ReviewRegion[];
  selectedRegionId?: string;
  onSelect: (region: ReviewRegion) => void;
}

export function PdfPreview({ previewUrls, regions, selectedRegionId, onSelect }: PdfPreviewProps) {
  return (
    <section className="pdf-preview" aria-label="PDF source and DOCX target preview">
      <div className="pdf-pages">
        {previewUrls.map((url, index) => (
          <figure key={url}>
            <img alt={`Source PDF page ${index + 1}`} loading="lazy" src={url} />
            <figcaption>Source page {index + 1}</figcaption>
          </figure>
        ))}
      </div>
      <div className="reference-preview">
        <div className="reference-preview__title">
          <FileOutput size={16} aria-hidden="true" />
          <strong>Reference Draft - Not for Signature</strong>
        </div>
        {regions.map((region) => (
          <button
            className={`reference-region${selectedRegionId === region.region_id ? " is-selected" : ""}`}
            key={region.region_id}
            onClick={() => onSelect(region)}
            type="button"
          >
            <span>{region.output_preview ?? "Not disclosed"}</span>
            <small>{titleCase(region.action)}</small>
          </button>
        ))}
      </div>
    </section>
  );
}
