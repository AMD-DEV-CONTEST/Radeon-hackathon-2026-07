import * as AlertDialog from "@radix-ui/react-alert-dialog";
import * as Tabs from "@radix-ui/react-tabs";
import {
  Ban,
  CheckCircle2,
  CircleAlert,
  FileDiff,
  GitBranch,
  Grid3X3,
  LoaderCircle,
  ShieldAlert,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { ApprovalPanel } from "../approvals/ApprovalPanel";
import { ReviewCopilot } from "../copilot/ReviewCopilot";
import { ExportPanel } from "../exports/ExportPanel";
import type {
  ApiState,
  Approval,
  Decision,
  DemoRole,
  DisclosureTask,
  ReviewData,
  ReviewRegion,
  Revision,
  Simulation,
} from "../../lib/types";
import {
  PolicySealApiError,
  confirmFormalContext,
  getReview,
  getRevisionApproval,
  requestApproval,
  resolveApproval,
  simulateContext,
} from "../../lib/api";
import { statusTone, titleCase } from "../../lib/utils";
import { SCENARIO_PRESETS } from "../tasks/presets";
import { ContextMatrix, type MatrixColumn } from "./ContextMatrix";
import { DecisionInspector } from "./DecisionInspector";
import { DocxPreview } from "./DocxPreview";
import { PdfPreview } from "./PdfPreview";
import { XlsxPreview } from "./XlsxPreview";

const MATRIX_PRESET_IDS = ["xlsx-internal", "xlsx-audit", "xlsx-bidder", "xlsx-personal"];
const MATRIX_LABELS: Record<string, string> = {
  "xlsx-internal": "Internal",
  "xlsx-audit": "Audit",
  "xlsx-bidder": "Bidder A",
  "xlsx-personal": "Personal email",
};

interface ReviewWorkspaceProps {
  task: DisclosureTask;
  revision: Revision;
  role: DemoRole;
  apiState: ApiState;
  onFormalRevision: (revision: Revision) => Promise<void>;
  onRevisionChanged: () => Promise<void>;
}

function contextKey(context: Revision["context"]): string {
  return [
    context.recipient,
    context.organization,
    context.recipient_id,
    context.purpose,
    context.channel,
    context.classification,
    context.policy_version,
  ].join("|");
}

function riskConclusion(status: Revision["status"] | undefined) {
  if (status === "blocked") {
    return { title: "Disclosure blocked", copy: "The selected channel or policy condition prohibits an output.", icon: Ban, tone: "danger" as const };
  }
  if (status === "awaiting_approval") {
    return { title: "Approval required", copy: "The generated revision is held until a separate reviewer approves the exact binding.", icon: ShieldAlert, tone: "warning" as const };
  }
  if (status === "processing_failed") {
    return { title: "Processing failed closed", copy: "No business output is available from this revision.", icon: CircleAlert, tone: "danger" as const };
  }
  return { title: "Minimum disclosure ready", copy: "Deterministic policy and residual checks completed for this context.", icon: CheckCircle2, tone: "success" as const };
}

export function ReviewWorkspace({
  task,
  revision,
  role,
  apiState,
  onFormalRevision,
  onRevisionChanged,
}: ReviewWorkspaceProps) {
  const [review, setReview] = useState<ReviewData>();
  const [simulations, setSimulations] = useState<Record<string, Simulation>>({});
  const [selectedColumnId, setSelectedColumnId] = useState<string>("formal");
  const [selectedRegionId, setSelectedRegionId] = useState<string>();
  const [selectedDecision, setSelectedDecision] = useState<Decision>();
  const [loadError, setLoadError] = useState<string>();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [approval, setApproval] = useState<Approval>();
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [approvalError, setApprovalError] = useState<string>();

  const formalPreset = useMemo(
    () =>
      SCENARIO_PRESETS.find(
        (preset) => contextKey({ ...preset.context, sha256: "" }) === contextKey(revision.context),
      ),
    [revision.context],
  );

  useEffect(() => {
    const controller = new AbortController();
    setReview(undefined);
    setLoadError(undefined);
    getReview(revision.id, controller.signal)
      .then((data) => {
        setReview(data);
        setSelectedRegionId(data.regions[0]?.region_id);
        setSelectedDecision(revision.decisions[0]);
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setLoadError(error instanceof Error ? error.message : "Review data is unavailable.");
        }
      });
    return () => controller.abort();
  }, [revision]);

  useEffect(() => {
    if (task.file_kind !== "xlsx") return;
    const controller = new AbortController();
    setSimulations({});
    setSelectedColumnId(formalPreset?.id ?? "formal");
    const presets = SCENARIO_PRESETS.filter(
      (preset) => MATRIX_PRESET_IDS.includes(preset.id) && preset.id !== formalPreset?.id,
    );
    void Promise.all(
      presets.map(async (preset) => {
        const simulation = await simulateContext(task.id, preset.context, controller.signal);
        setSimulations((current) => ({ ...current, [preset.id]: simulation }));
      }),
    ).catch((error) => {
      if (!controller.signal.aborted) {
        setLoadError(error instanceof Error ? error.message : "Matrix simulation failed.");
      }
    });
    return () => controller.abort();
  }, [formalPreset?.id, revision.id, task.file_kind, task.id]);

  useEffect(() => {
    const approvalStates = new Set(["awaiting_approval", "approved", "rejected"]);
    setApproval(undefined);
    setApprovalError(undefined);
    if (!approvalStates.has(revision.status)) return;
    const controller = new AbortController();
    getRevisionApproval(revision.id, controller.signal)
      .then(setApproval)
      .catch((caught) => {
        if (controller.signal.aborted) return;
        if (caught instanceof PolicySealApiError && caught.status === 404) return;
        setApprovalError(caught instanceof Error ? caught.message : "Approval data is unavailable.");
      });
    return () => controller.abort();
  }, [revision.id, revision.status]);

  const columns = useMemo<MatrixColumn[]>(() => {
    if (task.file_kind !== "xlsx") return [];
    return MATRIX_PRESET_IDS.map((presetId) => {
      const isFormal = formalPreset?.id === presetId;
      const simulation = simulations[presetId];
      return {
        id: presetId,
        label: MATRIX_LABELS[presetId],
        status: isFormal ? revision.status : simulation?.status,
        decisions: isFormal ? revision.decisions : simulation?.decisions,
        formal: isFormal,
      };
    });
  }, [formalPreset?.id, revision.decisions, revision.status, simulations, task.file_kind]);

  const selectedColumn = columns.find((column) => column.id === selectedColumnId);
  const selectedSimulation = selectedColumn?.formal ? undefined : simulations[selectedColumnId];
  const selectedRegion = review?.regions.find((region) => region.region_id === selectedRegionId);
  const activeStatus = selectedColumn?.status ?? revision.status;
  const conclusion = riskConclusion(activeStatus);
  const ConclusionIcon = conclusion.icon;
  const actionCounts = selectedColumn?.decisions?.reduce<Record<string, number>>((counts, item) => {
    counts[item.action] = (counts[item.action] ?? 0) + 1;
    return counts;
  }, {}) ?? revision.action_counts;

  function selectColumn(column: MatrixColumn) {
    setSelectedColumnId(column.id);
    const decision = column.decisions?.find((item) => item.region_id === selectedRegionId) ?? column.decisions?.[0];
    setSelectedDecision(decision);
    if (decision) setSelectedRegionId(decision.region_id);
  }

  function selectRegion(region: ReviewRegion) {
    setSelectedRegionId(region.region_id);
    const decision =
      selectedColumn?.decisions?.find((item) => item.region_id === region.region_id) ??
      revision.decisions.find((item) => item.region_id === region.region_id);
    setSelectedDecision(decision);
  }

  function selectCopilotLocation(location: string) {
    const region = review?.regions.find((item) => item.location === location);
    if (!region) return;
    setSelectedColumnId(formalPreset?.id ?? "formal");
    setSelectedRegionId(region.region_id);
    setSelectedDecision(
      revision.decisions.find((item) => item.region_id === region.region_id),
    );
  }

  async function makeFormal() {
    if (!selectedSimulation) return;
    setConfirming(true);
    try {
      const created = await confirmFormalContext(
        task.id,
        selectedSimulation.id,
        task.requester_id,
      );
      await onFormalRevision(created);
      setConfirmOpen(false);
    } finally {
      setConfirming(false);
    }
  }

  async function createApprovalRequest() {
    setApprovalBusy(true);
    setApprovalError(undefined);
    try {
      setApproval(await requestApproval(revision.id, task.requester_id));
    } catch (caught) {
      setApprovalError(caught instanceof Error ? caught.message : "Approval request failed.");
    } finally {
      setApprovalBusy(false);
    }
  }

  async function reviewApproval(operation: "approve" | "reject") {
    if (!approval) return;
    setApprovalBusy(true);
    setApprovalError(undefined);
    try {
      setApproval(await resolveApproval(approval, operation, "demo-policy-reviewer"));
      await onRevisionChanged();
    } catch (caught) {
      setApprovalError(caught instanceof Error ? caught.message : "Approval resolution failed.");
    } finally {
      setApprovalBusy(false);
    }
  }

  async function refreshAfterExport() {
    if (revision.status === "approved") {
      try {
        setApproval(await getRevisionApproval(revision.id));
      } catch {
        // The consumed export already succeeded; the task refresh remains authoritative.
      }
    }
    await onRevisionChanged();
  }

  if (!review) {
    return (
      <section className="review-loading" role="status">
        {loadError ? <CircleAlert size={20} aria-hidden="true" /> : <LoaderCircle className="spin" size={20} aria-hidden="true" />}
        <span>{loadError ?? "Loading local review evidence"}</span>
      </section>
    );
  }

  return (
    <section className="review-workspace" aria-label="Disclosure review workspace">
      <div className={`risk-conclusion risk-conclusion--${conclusion.tone}`}>
        <ConclusionIcon size={20} aria-hidden="true" />
        <span>
          <strong>{conclusion.title}</strong>
          <small>{conclusion.copy}</small>
        </span>
        <Badge tone={statusTone(activeStatus)}>{titleCase(activeStatus)}</Badge>
      </div>

      <div className="review-context-bar">
        <dl>
          <div><dt>Recipient</dt><dd>{titleCase((selectedSimulation?.context ?? revision.context).recipient)}</dd></div>
          <div><dt>Purpose</dt><dd>{titleCase((selectedSimulation?.context ?? revision.context).purpose)}</dd></div>
          <div><dt>Channel</dt><dd>{titleCase((selectedSimulation?.context ?? revision.context).channel)}</dd></div>
          <div><dt>Classification</dt><dd>{titleCase((selectedSimulation?.context ?? revision.context).classification)}</dd></div>
        </dl>
        <div className="action-counts" aria-label="Action counts">
          {Object.entries(actionCounts).map(([action, count]) => (
            <span key={action}><strong>{count}</strong>{titleCase(action)}</span>
          ))}
        </div>
      </div>

      {selectedSimulation ? (
        <div className="simulation-bar">
          <GitBranch size={16} aria-hidden="true" />
          <span><strong>Simulation only</strong> / non-downloadable until confirmed as a new revision</span>
          <Button
            disabled={role !== "requester"}
            size="small"
            onClick={() => setConfirmOpen(true)}
          >
            Set as formal context
          </Button>
        </div>
      ) : null}

      <Tabs.Root className="review-tabs" defaultValue={task.file_kind === "xlsx" ? "matrix" : "document"}>
        <Tabs.List aria-label="Review view" className="review-tab-list">
          {task.file_kind === "xlsx" ? (
            <Tabs.Trigger value="matrix"><Grid3X3 size={15} aria-hidden="true" />Matrix</Tabs.Trigger>
          ) : null}
          <Tabs.Trigger value="document"><FileDiff size={15} aria-hidden="true" />Document</Tabs.Trigger>
        </Tabs.List>

        {task.file_kind === "xlsx" ? (
          <Tabs.Content value="matrix">
            <ContextMatrix
              columns={columns}
              regions={review.regions}
              selectedColumnId={selectedColumnId}
              selectedRegionId={selectedRegionId}
              onSelectColumn={selectColumn}
              onSelectDecision={(column, decision, region) => {
                setSelectedColumnId(column.id);
                setSelectedDecision(decision);
                setSelectedRegionId(region.region_id);
              }}
            />
          </Tabs.Content>
        ) : null}

        <Tabs.Content value="document">
          {task.file_kind === "xlsx" ? (
            <XlsxPreview regions={review.regions} selectedRegionId={selectedRegionId} onSelect={selectRegion} />
          ) : task.file_kind === "docx" ? (
            <DocxPreview regions={review.regions} selectedRegionId={selectedRegionId} onSelect={selectRegion} />
          ) : (
            <PdfPreview previewUrls={review.preview_urls} regions={review.regions} selectedRegionId={selectedRegionId} onSelect={selectRegion} />
          )}
        </Tabs.Content>
      </Tabs.Root>

      <DecisionInspector
        contextLabel={selectedColumn?.label ?? titleCase(revision.context.recipient)}
        decision={selectedDecision}
        evidence={review.evidence}
        region={selectedRegion}
      />

      {!selectedSimulation ? (
        <>
          <div className="review-operations" aria-label="Formal revision controls">
            <ApprovalPanel
              approval={approval}
              busy={approvalBusy}
              error={approvalError}
              revision={revision}
              role={role}
              task={task}
              onRequest={createApprovalRequest}
              onResolve={reviewApproval}
            />
            <ExportPanel
              approval={approval}
              revision={revision}
              onBusinessExported={refreshAfterExport}
            />
          </div>
          <ReviewCopilot
            apiState={apiState}
            revision={revision}
            role={role}
            selectedLocation={selectedRegion?.location}
            task={task}
            onApprovalCreated={(created) => setApproval(created)}
            onSelectLocation={selectCopilotLocation}
          />
        </>
      ) : null}

      <AlertDialog.Root open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="dialog-overlay" />
          <AlertDialog.Content className="alert-dialog-content">
            <div className="alert-dialog-icon"><GitBranch size={20} aria-hidden="true" /></div>
            <AlertDialog.Title>Create formal revision?</AlertDialog.Title>
            <AlertDialog.Description>
              This creates and analyzes a new immutable revision for {selectedColumn?.label}. The current revision remains unchanged.
            </AlertDialog.Description>
            <div className="dialog-actions">
              <AlertDialog.Cancel asChild><Button disabled={confirming}>Cancel</Button></AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <Button disabled={confirming} variant="primary" onClick={() => void makeFormal()}>
                  {confirming ? "Creating revision" : "Create formal revision"}
                </Button>
              </AlertDialog.Action>
            </div>
            <AlertDialog.Cancel className="alert-dialog-close" aria-label="Close confirmation"><X size={16} /></AlertDialog.Cancel>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </section>
  );
}
