import {
  Activity,
  ArrowUpRight,
  CheckCircle2,
  CircleDot,
  Cpu,
  Send,
  Sparkles,
} from "lucide-react";
import {
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";
import { useOutletContext } from "react-router-dom";

import { MotionWrapper } from "../components/motion/MotionWrapper";
import { Button } from "../components/ui/Button";
import { StatusBadge } from "../components/ui/StatusBadge";
import {
  useEvents,
  RuntimeStatusCard,
  useWorkspace,
  type LifecyclePhase,
  type ViewText,
  type WorkspaceContextSignal,
} from "../features/runtime";
import { useI18n } from "../i18n/I18nContext";
import type { TranslationKey } from "../i18n/messages";
import type { WorkspaceOutletContext } from "../layouts/AppShell";
import styles from "./WorkspacePage.module.css";

const lifecycleStages = [
  "lifecycle.detected",
  "lifecycle.analyzing",
  "lifecycle.review",
  "lifecycle.task",
  "lifecycle.evidence",
  "lifecycle.closed",
] as const satisfies readonly TranslationKey[];

const lifecycleIndex: Record<
  Exclude<LifecyclePhase, "failed">,
  number
> = {
  detected: 0,
  analysis: 1,
  review: 2,
  task: 3,
  evidence: 4,
  resolved: 5,
};

export function WorkspacePage() {
  const { t, text } = useI18n();
  const workspaceResource = useWorkspace();
  const { data: workspace } = workspaceResource;
  const { events } = useEvents();
  const { selectedEventId, openActionPanel } =
    useOutletContext<WorkspaceOutletContext>();
  const [instruction, setInstruction] = useState("");
  const [hasLocalFeedback, setHasLocalFeedback] = useState(false);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!instruction.trim()) {
      return;
    }

    setHasLocalFeedback(true);
  };

  if (!workspace) {
    const message =
      workspaceResource.error
        ? t("workspace.unavailable")
        : workspaceResource.status === "idle" ||
            workspaceResource.status === "loading" ||
            workspaceResource.status === "refreshing"
          ? t("workspace.loading")
          : t("shell.footer.offline");

    return (
      <div
        className={`${styles.page} ${styles.resourceState}`}
        role={workspaceResource.error ? "alert" : "status"}
      >
        <p>{message}</p>
        {workspaceResource.error ? (
          <Button
            variant="secondary"
            onClick={workspaceResource.refresh}
          >
            {t("workspace.retry")}
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <MotionWrapper className={styles.siteContext} preset="rise">
        <div className={styles.siteIdentity}>
          <p>{t("workspace.contextLabel")}</p>
          <h1>{text(workspace.site.name)}</h1>
          {workspace.site.observationLabel ? (
            <span>{text(workspace.site.observationLabel)}</span>
          ) : null}
        </div>
        <div className={styles.siteSignals}>
          {workspace.contextSignals.map((signal) => (
            <ContextSignal
              key={signal.id}
              icon={contextSignalIcon(signal.id)}
              label={text(signal.label)}
              tone={signal.tone}
            />
          ))}
        </div>
      </MotionWrapper>

      {workspaceResource.status === "error" ? (
        <p className={styles.staleNotice} role="status">
          {t("workspace.stale")}
        </p>
      ) : null}

      <MotionWrapper preset="rise" order={1}>
        <RuntimeStatusCard />
      </MotionWrapper>

      <MotionWrapper
        className={styles.eventField}
        preset="rise"
        order={2}
      >
        <header className={styles.eventHeader}>
          <div>
            <span className={styles.eventIcon} aria-hidden="true">
              <Activity />
            </span>
            <div>
              <h2>{t("activity.title")}</h2>
              <p>{t("activity.description")}</p>
            </div>
          </div>
          <StatusBadge tone="info">
            {t(
              workspaceResource.source === "mock"
                ? "workspace.mockBadge"
                : "workspace.runtimeBadge",
            )}
          </StatusBadge>
        </header>

        <div className={styles.eventList}>
          {events.length === 0 ? (
            <p className={styles.eventEmpty} role="status">
              {t("workspace.empty")}
            </p>
          ) : null}
          {events.map((event) => (
            <button
              className={styles.eventRow}
              data-selected={event.id === selectedEventId}
              data-severity={event.severity}
              data-status={event.runtimeStatus}
              key={event.id}
              type="button"
              aria-pressed={event.id === selectedEventId}
              aria-label={`${t("activity.openContext")}: ${text(event.title)}`}
              onClick={(clickEvent) =>
                openActionPanel(event.id, clickEvent.currentTarget)
              }
            >
              <span className={styles.eventMarker} aria-hidden="true" />
              <span className={styles.eventBody}>
                <span className={styles.eventMeta}>
                  <span>
                    {event.sourceLabel
                      ? text(event.sourceLabel)
                      : "—"}
                  </span>
                  <time>
                    {event.occurredLabel
                      ? text(event.occurredLabel)
                      : (event.occurredAt ?? "—")}
                  </time>
                </span>
                <strong>{text(event.title)}</strong>
                <span className={styles.eventDetail}>
                  {event.detail ? text(event.detail) : ""}
                </span>
                <span className={styles.eventState}>
                  <span className={styles.stateHeading}>
                    <StatusBadge tone={event.severity}>
                      {text(event.severityLabel)}
                    </StatusBadge>
                    <span>{text(event.statusLabel)}</span>
                  </span>
                  <LifecycleProjection
                    phase={event.lifecyclePhase}
                    statusLabel={event.statusLabel}
                    isTerminal={event.isTerminal}
                  />
                </span>
              </span>
              <ArrowUpRight
                className={styles.eventArrow}
                aria-hidden="true"
                size={17}
              />
            </button>
          ))}
        </div>
      </MotionWrapper>

      <MotionWrapper
        className={styles.commandDock}
        preset="rise"
        order={4}
      >
        <div className={styles.commandIdentity}>
          <Sparkles aria-hidden="true" size={17} />
          <div>
            <h2>{t("command.title")}</h2>
            <p>{t("command.description")}</p>
          </div>
        </div>
        <form className={styles.commandForm} onSubmit={handleSubmit}>
          <label className={styles.srOnly} htmlFor="workspace-command">
            {t("command.label")}
          </label>
          <input
            id="workspace-command"
            value={instruction}
            placeholder={t("command.placeholder")}
            onChange={(event) => {
              setInstruction(event.target.value);
              setHasLocalFeedback(false);
            }}
          />
          <Button
            className={styles.commandSubmit}
            type="submit"
            disabled={!instruction.trim()}
          >
            <Send aria-hidden="true" size={16} />
            <span>{t("command.submit")}</span>
          </Button>
        </form>
        <div className={styles.quickCommands}>
          {workspace.commandSuggestions.map((suggestion) => (
            <button
              key={suggestion.id}
              type="button"
              onClick={() => {
                setInstruction(text(suggestion.label));
                setHasLocalFeedback(false);
              }}
            >
              {text(suggestion.label)}
            </button>
          ))}
        </div>
        <p className={styles.commandFeedback} role="status" aria-live="polite">
          {hasLocalFeedback ? t("command.feedback") : ""}
        </p>
      </MotionWrapper>
    </div>
  );
}

interface ContextSignalProps {
  icon: React.ReactNode;
  label: string;
  tone: WorkspaceContextSignal["tone"];
}

function ContextSignal({ icon, label, tone }: ContextSignalProps) {
  return (
    <div className={styles.contextSignal} data-tone={tone}>
      <span aria-hidden="true">{icon}</span>
      <strong>{label}</strong>
    </div>
  );
}

function LifecycleProjection({
  phase,
  statusLabel,
  isTerminal,
}: {
  phase: LifecyclePhase;
  statusLabel: ViewText;
  isTerminal: boolean;
}) {
  const { t, text } = useI18n();
  const isExceptional = phase === "failed";
  const currentIndex = isExceptional ? -1 : lifecycleIndex[phase];
  const currentStage =
    currentIndex >= 0
      ? (lifecycleStages[currentIndex] ?? lifecycleStages[0])
      : lifecycleStages[0];
  const currentLabel = isExceptional
    ? text(statusLabel)
    : t(currentStage);

  return (
    <span
      className={styles.lifecycle}
      data-exceptional={isExceptional}
      aria-label={`${t("lifecycle.label")}: ${currentLabel}`}
    >
      <span className={styles.lifecycleTrack} aria-hidden="true">
        <span
          className={styles.lifecycleProgress}
          style={
            {
              "--lifecycle-progress":
                currentIndex < 0 ? 0 : currentIndex / 5,
            } as CSSProperties
          }
        />
        {lifecycleStages.map((stage, index) => (
          <span
            className={styles.lifecycleStep}
            data-complete={
              currentIndex >= 0 && index <= currentIndex
            }
            data-current={
              currentIndex >= 0 && index === currentIndex
            }
            key={stage}
          />
        ))}
      </span>
      <span className={styles.lifecycleLabel}>
        {isTerminal && phase === "resolved" ? (
          <CheckCircle2 aria-hidden="true" size={13} />
        ) : null}
        {currentLabel}
      </span>
    </span>
  );
}

function contextSignalIcon(id: string): React.ReactNode {
  if (id === "attention") {
    return <CircleDot />;
  }
  if (id === "edge") {
    return <Cpu />;
  }
  return <Sparkles />;
}
