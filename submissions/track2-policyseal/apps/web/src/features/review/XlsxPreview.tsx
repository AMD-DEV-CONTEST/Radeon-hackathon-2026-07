import type { ReviewRegion } from "../../lib/types";
import { titleCase } from "../../lib/utils";

interface XlsxPreviewProps {
  regions: ReviewRegion[];
  selectedRegionId?: string;
  onSelect: (region: ReviewRegion) => void;
}

export function XlsxPreview({ regions, selectedRegionId, onSelect }: XlsxPreviewProps) {
  return (
    <section className="document-preview" aria-label="XLSX synchronized preview">
      <div className="preview-table preview-table--header">
        <span>Cell</span>
        <span>Source</span>
        <span>Target</span>
        <span>Action</span>
      </div>
      <div className="preview-table__body">
        {regions.map((region) => (
          <button
            className={`preview-table preview-table--row${selectedRegionId === region.region_id ? " is-selected" : ""}`}
            key={region.region_id}
            onClick={() => onSelect(region)}
            type="button"
          >
            <strong title={region.location}>{region.location.replace("xlsx:", "")}</strong>
            <span>{region.source_text}</span>
            <span>{region.output_preview ?? "Not disclosed"}</span>
            <small>{titleCase(region.action)}</small>
          </button>
        ))}
      </div>
    </section>
  );
}
