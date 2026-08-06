import {
  ArrowRight,
  BrainCircuit,
  FileText,
  LockKeyhole,
  ShieldAlert,
  UserRoundCheck,
  X,
} from "lucide-react";
import { useEffect, useRef } from "react";

import { HumanReviewActionPanel } from "../../features/human-review";
import type {
  ActionSummary,
  EventView,
  ViewText,
} from "../../features/runtime";
import { useI18n } from "../../i18n/I18nContext";
import { MotionOverlay } from "../motion/MotionOverlay";
import { Button } from "../ui/Button";
import { StatusBadge } from "../ui/StatusBadge";
import styles from "./AgentActionPanel.module.css";

interface AgentActionPanelProps {
  isOpen: boolean;
  event: EventView;
  action: ActionSummary;
  employeeName: ViewText | null;
  source: "mock" | "http";
  onRuntimeChanged: () => void;
  onClose: () => void;
}

export function AgentActionPanel({
  isOpen,
  event,
  action,
  employeeName,
  source,
  onRuntimeChanged,
  onClose,
}: AgentActionPanelProps) {
  const { t, text } = useI18n();
  const contentRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const focusable =
        contentRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
      const first = focusable?.[0];
      const last = focusable?.[focusable.length - 1];

      if (!first || !last) {
        return;
      }

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  return (
    <MotionOverlay
      isVisible={isOpen}
      overlayClassName={styles.overlay}
      surfaceClassName={styles.panel}
      labelledBy="action-panel-title"
      describedBy="action-panel-description"
      onBackdropMouseDown={onClose}
    >
      <div ref={contentRef} className={styles.content}>
        <header className={styles.header}>
          <div>
            <p className={styles.kicker}>{t("actionPanel.title")}</p>
            <h2 id="action-panel-title">{text(event.title)}</h2>
            <p id="action-panel-description">
              {t("actionPanel.description")}
            </p>
          </div>
          <Button
            ref={closeButtonRef}
            className={styles.closeButton}
            variant="secondary"
            aria-label={t("actionPanel.close")}
            onClick={onClose}
          >
            <X aria-hidden="true" size={18} />
          </Button>
        </header>

        <div className={styles.eventMeta}>
          <span>
            {event.sourceLabel ? text(event.sourceLabel) : "—"}
          </span>
          <time>
            {event.occurredLabel
              ? text(event.occurredLabel)
              : (event.occurredAt ?? "—")}
          </time>
          <StatusBadge tone={event.severity}>
            {text(event.statusLabel)}
          </StatusBadge>
        </div>

        {source === "http" ? (
          <HumanReviewActionPanel
            eventId={event.id}
            isActive={isOpen}
            employeeName={employeeName}
            responsibilityName={event.sourceLabel}
            onRuntimeChanged={onRuntimeChanged}
          />
        ) : (
          <div className={styles.fields}>
            <ActionField
              icon={<FileText />}
              label={t("summary.facts")}
              value={action.facts.map(text).join(" ") || "—"}
            />
            <ActionField
              icon={<BrainCircuit />}
              label={t("summary.analysis")}
              value={
                action.aiUnderstanding
                  ? text(action.aiUnderstanding)
                  : "—"
              }
            />
            <ActionField
              icon={<ShieldAlert />}
              label={t("summary.risk")}
              value={
                action.risk.explanation
                  ? text(action.risk.explanation)
                  : "—"
              }
              tone="attention"
            />
            <ActionField
              icon={<ArrowRight />}
              label={t("summary.next")}
              value={
                action.suggestedAction
                  ? text(action.suggestedAction)
                  : "—"
              }
            />
            <ActionField
              icon={<UserRoundCheck />}
              label={t("actionPanel.decision")}
              value={
                action.humanDecision
                  ? text(action.humanDecision)
                  : "—"
              }
            />
          </div>
        )}

        <footer className={styles.boundary}>
          <LockKeyhole aria-hidden="true" size={16} />
          <span>
            {t(
              source === "mock"
                ? "actionPanel.mockBoundary"
                : "actionPanel.runtimeBoundary",
            )}
          </span>
        </footer>
      </div>
    </MotionOverlay>
  );
}

interface ActionFieldProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone?: "neutral" | "attention";
}

function ActionField({
  icon,
  label,
  value,
  tone = "neutral",
}: ActionFieldProps) {
  return (
    <section className={styles.field} data-tone={tone}>
      <span className={styles.fieldIcon} aria-hidden="true">
        {icon}
      </span>
      <div>
        <h3>{label}</h3>
        <p>{value}</p>
      </div>
    </section>
  );
}
