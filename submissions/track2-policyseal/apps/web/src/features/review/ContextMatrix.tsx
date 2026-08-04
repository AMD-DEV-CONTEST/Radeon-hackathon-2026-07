import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Ban,
  Check,
  CircleDashed,
  Clock3,
  EyeOff,
  Filter,
  ScanEye,
  SlidersHorizontal,
} from "lucide-react";
import { useMemo, useRef } from "react";

import { Badge } from "../../components/ui/Badge";
import type { Action, Decision, ReviewRegion, RevisionStatus } from "../../lib/types";
import { actionTone, statusTone, titleCase } from "../../lib/utils";

export interface MatrixColumn {
  id: string;
  label: string;
  status?: RevisionStatus;
  decisions?: Decision[];
  formal: boolean;
}

interface ContextMatrixProps {
  regions: ReviewRegion[];
  columns: MatrixColumn[];
  selectedColumnId: string;
  selectedRegionId?: string;
  onSelectColumn: (column: MatrixColumn) => void;
  onSelectDecision: (
    column: MatrixColumn,
    decision: Decision,
    region: ReviewRegion,
  ) => void;
}

function ActionIcon({ action }: { action: Action }) {
  const props = { size: 14, strokeWidth: 2 } as const;
  if (action === "keep") return <Check {...props} aria-hidden="true" />;
  if (action === "mask") return <ScanEye {...props} aria-hidden="true" />;
  if (action === "remove") return <EyeOff {...props} aria-hidden="true" />;
  if (action === "filter") return <Filter {...props} aria-hidden="true" />;
  if (action === "generalize") return <SlidersHorizontal {...props} aria-hidden="true" />;
  if (action === "require_approval") return <Clock3 {...props} aria-hidden="true" />;
  return <Ban {...props} aria-hidden="true" />;
}

export function ContextMatrix({
  regions,
  columns,
  selectedColumnId,
  selectedRegionId,
  onSelectColumn,
  onSelectDecision,
}: ContextMatrixProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const orderedRegions = useMemo(
    () => [...regions].sort((left, right) => left.order - right.order),
    [regions],
  );
  const virtualizer = useVirtualizer({
    count: orderedRegions.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 42,
    overscan: 8,
    initialRect: { width: 760, height: 330 },
  });
  const measuredRows = virtualizer.getVirtualItems();
  const visibleRows =
    measuredRows.length > 0
      ? measuredRows
      : orderedRegions.map((_region, index) => ({
          index,
          start: index * 42,
          key: `fallback-${index}`,
        }));

  return (
    <section className="context-matrix" aria-labelledby="matrix-title">
      <div className="matrix-heading">
        <div>
          <p className="section-label">Four-recipient comparison</p>
          <h3 id="matrix-title">Disclosure action matrix</h3>
        </div>
        <span>{regions.length} stable regions</span>
      </div>

      <div className="matrix-scroll-x">
        <div className="matrix-grid matrix-grid--header" role="row">
          <div className="matrix-field-header" role="columnheader">Stable location</div>
          {columns.map((column) => (
            <button
              aria-pressed={selectedColumnId === column.id}
              className={`matrix-column-header${selectedColumnId === column.id ? " is-selected" : ""}`}
              key={column.id}
              onClick={() => onSelectColumn(column)}
              role="columnheader"
              type="button"
            >
              <strong>{column.label}</strong>
              <span>
                {column.formal ? <Badge tone="info">Formal</Badge> : <Badge>What-if</Badge>}
                {column.status ? (
                  <Badge tone={statusTone(column.status)}>{titleCase(column.status)}</Badge>
                ) : (
                  <CircleDashed className="spin" size={13} aria-label="Loading" />
                )}
              </span>
            </button>
          ))}
        </div>

        <div className="matrix-viewport" ref={scrollRef} role="rowgroup">
          <div
            className="matrix-virtual-space"
            style={{ height: `${virtualizer.getTotalSize()}px` }}
          >
            {visibleRows.map((virtualRow) => {
              const region = orderedRegions[virtualRow.index];
              return (
                <div
                  className={`matrix-grid matrix-grid--row${selectedRegionId === region.region_id ? " is-selected" : ""}`}
                  key={region.region_id}
                  role="row"
                  style={{ transform: `translateY(${virtualRow.start}px)` }}
                >
                  <div className="matrix-location" role="rowheader" title={region.location}>
                    <strong>{region.location.replace(/^(xlsx|docx|pdf):/, "")}</strong>
                    <small>{titleCase(region.category)}</small>
                  </div>
                  {columns.map((column) => {
                    const decision = column.decisions?.find(
                      (item) => item.region_id === region.region_id,
                    );
                    return decision ? (
                      <button
                        aria-label={`${column.label}, ${region.location}, ${titleCase(decision.action)}`}
                        className={`matrix-action matrix-action--${actionTone(decision.action)}${selectedColumnId === column.id && selectedRegionId === region.region_id ? " is-selected" : ""}`}
                        key={column.id}
                        onClick={() => onSelectDecision(column, decision, region)}
                        role="gridcell"
                        type="button"
                      >
                        <ActionIcon action={decision.action} />
                        <span>{titleCase(decision.action)}</span>
                      </button>
                    ) : (
                      <div className="matrix-action matrix-action--loading" key={column.id} role="gridcell">
                        <CircleDashed className="spin" size={13} aria-hidden="true" />
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
