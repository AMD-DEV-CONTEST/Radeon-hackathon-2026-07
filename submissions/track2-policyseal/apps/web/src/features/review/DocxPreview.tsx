import type { ReviewRegion } from "../../lib/types";
import { titleCase } from "../../lib/utils";

interface DocxPreviewProps {
  regions: ReviewRegion[];
  selectedRegionId?: string;
  onSelect: (region: ReviewRegion) => void;
}

export function DocxPreview({ regions, selectedRegionId, onSelect }: DocxPreviewProps) {
  return (
    <section className="docx-preview" aria-label="DOCX synchronized preview">
      {regions.map((region) => (
        <button
          className={`document-region${selectedRegionId === region.region_id ? " is-selected" : ""}`}
          key={region.region_id}
          onClick={() => onSelect(region)}
          type="button"
        >
          <span className="document-region__meta">
            <strong>{region.location.replace("docx:", "")}</strong>
            <small>{titleCase(region.action)}</small>
          </span>
          <span className="document-region__copy">
            <span>{region.source_text}</span>
            <span>{region.output_preview ?? "Not disclosed"}</span>
          </span>
        </button>
      ))}
    </section>
  );
}
