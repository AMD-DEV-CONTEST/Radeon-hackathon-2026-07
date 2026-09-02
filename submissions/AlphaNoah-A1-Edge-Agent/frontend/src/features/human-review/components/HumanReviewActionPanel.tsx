import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  ClipboardCheck,
  RotateCw,
  ShieldCheck,
  UserRoundCheck,
  XCircle,
} from "lucide-react";

import { Button } from "../../../components/ui/Button";
import type { ViewText } from "../../runtime";
import { useI18n } from "../../../i18n/I18nContext";
import type { TranslationKey } from "../../../i18n/messages";
import { useHumanReview } from "../hooks/useHumanReview";
import type {
  HumanReviewSnapshot,
  HumanReviewViewState,
} from "../models/humanReview";
import styles from "./HumanReviewActionPanel.module.css";

interface HumanReviewActionPanelProps {
  readonly eventId: string;
  readonly isActive: boolean;
  readonly employeeName: ViewText | null;
  readonly responsibilityName: ViewText | null;
  readonly onRuntimeChanged: () => void;
}

export function HumanReviewActionPanel({
  eventId,
  isActive,
  employeeName,
  responsibilityName,
  onRuntimeChanged,
}: HumanReviewActionPanelProps) {
  const { t, text } = useI18n();
  const resource = useHumanReview(eventId, isActive);
  const snapshot = resource.data;
  const isSubmitting = resource.status === "submitting";
  const linkedRole = employeeName ?? responsibilityName;

  const run = async (operation: () => Promise<boolean>) => {
    if (await operation()) {
      onRuntimeChanged();
    }
  };

  if (!snapshot && resource.status === "loading") {
    return (
      <section className={styles.card} aria-labelledby="review-card-title">
        <CardHeading />
        <p className={styles.resourceState} role="status">
          <RotateCw aria-hidden="true" />
          {t("humanReview.loading")}
        </p>
      </section>
    );
  }

  if (!snapshot && resource.error) {
    return (
      <section className={styles.card} aria-labelledby="review-card-title">
        <CardHeading />
        <div className={styles.error} role="alert">
          <AlertTriangle aria-hidden="true" />
          <div>
            <strong>{t("humanReview.error")}</strong>
            <p>{t("humanReview.errorDescription")}</p>
          </div>
        </div>
        <Button variant="secondary" onClick={resource.refresh}>
          <RotateCw aria-hidden="true" size={15} />
          {t("humanReview.retry")}
        </Button>
      </section>
    );
  }

  if (!snapshot) {
    return null;
  }

  return (
    <section
      className={styles.card}
      data-review-state={snapshot.state}
      aria-labelledby="review-card-title"
    >
      <CardHeading />

      {snapshot.analysis ? (
        <div className={styles.recommendation}>
          <ReviewFact
            label={t("humanReview.finding")}
            value={snapshot.analysis.finding}
          />
          <ReviewFact
            label={t("humanReview.analysis")}
            value={snapshot.analysis.analysis}
          />
          <ReviewFact
            label={t("humanReview.recommendation")}
            value={
              snapshot.analysis.recommendation ??
              t("humanReview.recommendationUnavailable")
            }
          />
          <div className={styles.confidenceRow}>
            <span>{t("humanReview.confidence")}</span>
            <strong>
              {formatConfidence(snapshot.analysis.confidence)}
            </strong>
            <span className={styles.confidenceTrack} aria-hidden="true">
              <span
                style={{
                  width: `${confidencePercent(snapshot.analysis.confidence)}%`,
                }}
              />
            </span>
          </div>
        </div>
      ) : (
        <p className={styles.resourceState} role="status">
          {t("humanReview.analysisUnavailable")}
        </p>
      )}

      <div className={styles.decisionDivider} />

      <div className={styles.decisionHeader}>
        <span className={styles.decisionIcon} aria-hidden="true">
          {stateIcon(snapshot.state)}
        </span>
        <div>
          <p>{t("humanReview.decision")}</p>
          <strong>{t(stateTitle(snapshot.state))}</strong>
          <span>{stateDescription(snapshot, t)}</span>
        </div>
      </div>

      {linkedRole ? (
        <div className={styles.employeeLink}>
          <UserRoundCheck aria-hidden="true" />
          <div>
            <span>{text(linkedRole)}</span>
            <strong>{t(employeeState(snapshot.state))}</strong>
          </div>
        </div>
      ) : null}

      {resource.error ? (
        <div className={styles.inlineError} role="alert">
          <AlertTriangle aria-hidden="true" />
          <span>{t("humanReview.actionError")}</span>
        </div>
      ) : null}

      {snapshot.state === "pending" ? (
        <div className={styles.actions}>
          <Button
            disabled={isSubmitting}
            onClick={() => void run(resource.approve)}
          >
            <CheckCircle2 aria-hidden="true" size={16} />
            {isSubmitting
              ? t("humanReview.submitting")
              : t("humanReview.approve")}
          </Button>
          <Button
            variant="secondary"
            disabled={isSubmitting}
            onClick={() => void run(resource.reject)}
          >
            <XCircle aria-hidden="true" size={16} />
            {isSubmitting
              ? t("humanReview.submitting")
              : t("humanReview.reject")}
          </Button>
        </div>
      ) : null}

      {snapshot.state === "approved" && snapshot.task === null ? (
        <div className={styles.actions}>
          <Button
            disabled={isSubmitting}
            onClick={() => void run(resource.createTask)}
          >
            <ClipboardCheck aria-hidden="true" size={16} />
            {isSubmitting
              ? t("humanReview.submitting")
              : t("humanReview.createTask")}
          </Button>
        </div>
      ) : null}

      <footer className={styles.runtimeBoundary}>
        <ShieldCheck aria-hidden="true" />
        <span>{t("humanReview.runtimeBoundary")}</span>
      </footer>
    </section>
  );
}

function CardHeading() {
  const { t } = useI18n();
  return (
    <header className={styles.heading}>
      <span aria-hidden="true">
        <BrainCircuit />
      </span>
      <div>
        <p>{t("humanReview.eyebrow")}</p>
        <h3 id="review-card-title">{t("humanReview.title")}</h3>
      </div>
    </header>
  );
}

function ReviewFact({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.fact}>
      <span>{label}</span>
      <p>{value}</p>
    </div>
  );
}

function confidencePercent(confidence: number): number {
  return Math.round(Math.min(1, Math.max(0, confidence)) * 100);
}

function formatConfidence(confidence: number): string {
  return `${confidencePercent(confidence)}%`;
}

function stateIcon(state: HumanReviewViewState): React.ReactNode {
  if (state === "rejected") {
    return <XCircle />;
  }
  if (state === "pending") {
    return <UserRoundCheck />;
  }
  return <CheckCircle2 />;
}

function stateTitle(
  state: HumanReviewViewState,
):
  | "humanReview.pending"
  | "humanReview.approved"
  | "humanReview.rejected"
  | "humanReview.closed"
  | "humanReview.notRequired" {
  switch (state) {
    case "pending":
      return "humanReview.pending";
    case "approved":
      return "humanReview.approved";
    case "rejected":
      return "humanReview.rejected";
    case "closed":
      return "humanReview.closed";
    case "not_required":
      return "humanReview.notRequired";
  }
}

function stateDescription(
  snapshot: HumanReviewSnapshot,
  t: (key: TranslationKey) => string,
): string {
  if (snapshot.state === "approved") {
    return snapshot.task
      ? t("humanReview.taskCreated")
      : t("humanReview.taskPending");
  }
  switch (snapshot.state) {
    case "pending":
      return t("humanReview.pendingDescription");
    case "rejected":
      return t("humanReview.rejectedDescription");
    case "closed":
      return t("humanReview.closedDescription");
    case "not_required":
      return t("humanReview.notRequiredDescription");
  }
}

function employeeState(
  state: HumanReviewViewState,
):
  | "humanReview.employeeWaiting"
  | "humanReview.employeeWorking"
  | "humanReview.employeeRejected"
  | "humanReview.employeeCompleted" {
  if (state === "pending") {
    return "humanReview.employeeWaiting";
  }
  if (state === "closed") {
    return "humanReview.employeeCompleted";
  }
  if (state === "rejected" || state === "not_required") {
    return "humanReview.employeeRejected";
  }
  return "humanReview.employeeWorking";
}
