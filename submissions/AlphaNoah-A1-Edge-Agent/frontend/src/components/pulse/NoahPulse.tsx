import { ArrowUpRight, Radio, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import type { PulseNotice } from "../../features/runtime";
import { useI18n } from "../../i18n/I18nContext";
import { MotionMorphingSurface } from "../motion/MotionMorphingSurface";
import styles from "./NoahPulse.module.css";

interface NoahPulseProps {
  notice?: PulseNotice;
  loading?: boolean;
  unavailable?: boolean;
  onOpenAction?: (
    eventId: string,
    trigger?: HTMLElement,
  ) => void;
}

export function NoahPulse({
  notice,
  loading = false,
  unavailable = false,
  onOpenAction,
}: NoahPulseProps) {
  const { t, text } = useI18n();
  const [isExpanded, setIsExpanded] = useState(false);
  const capsuleRef = useRef<HTMLElement | null>(null);
  const pendingActionRef = useRef<string | null>(null);
  const shouldRestoreFocusRef = useRef(false);
  const activeNotice = unavailable ? undefined : notice;
  const state = unavailable
    ? "unavailable"
    : (activeNotice?.kind ?? "idle");
  const canExpand = Boolean(activeNotice);

  const closePulse = useCallback((restoreFocus = true) => {
    shouldRestoreFocusRef.current = restoreFocus;
    setIsExpanded(false);
  }, []);

  const setCapsuleRef = useCallback(
    (node: HTMLButtonElement | null) => {
      capsuleRef.current = node;
      if (!node) {
        return;
      }

      const pendingEventId = pendingActionRef.current;
      if (pendingEventId) {
        pendingActionRef.current = null;
        onOpenAction?.(pendingEventId, node);
        return;
      }

      if (!shouldRestoreFocusRef.current) {
        return;
      }

      shouldRestoreFocusRef.current = false;
      node.focus();
    },
    [onOpenAction],
  );

  const setCloseButtonRef = useCallback(
    (node: HTMLButtonElement | null) => {
      if (node) {
        node.focus();
      }
    },
    [],
  );

  useEffect(() => {
    if (!isExpanded || !activeNotice) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }

      event.preventDefault();
      closePulse();
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [activeNotice, closePulse, isExpanded]);

  useEffect(() => {
    if (unavailable && isExpanded) {
      setIsExpanded(false);
    }
  }, [isExpanded, unavailable]);

  const handleOpenAction = () => {
    if (!activeNotice) {
      return;
    }

    pendingActionRef.current = activeNotice.eventId;
    closePulse(false);
  };

  const capsuleVisual = (
    <>
      <span className={styles.icon}>
        <Radio aria-hidden="true" size={15} />
      </span>
      <span className={styles.copy}>
        <strong>
          {activeNotice
            ? text(activeNotice.title)
            : t("pulse.label")}
        </strong>
        <small>
          {unavailable
            ? t("pulse.unavailable")
            : activeNotice
              ? t("pulse.reviewNeeded")
              : loading
                ? t("pulse.loading")
                : t("pulse.state.idle")}
        </small>
      </span>
    </>
  );

  const collapsedContent = canExpand ? (
    <button
      ref={setCapsuleRef}
      className={styles.capsule}
      type="button"
      aria-label={t("pulse.open")}
      aria-haspopup="dialog"
      aria-expanded={isExpanded}
      aria-controls="noah-pulse-expanded"
      onClick={() => setIsExpanded(true)}
    >
      {capsuleVisual}
    </button>
  ) : (
    <div
      className={styles.capsule}
      role="status"
      aria-live="polite"
    >
      {capsuleVisual}
    </div>
  );

  const expandedContent = activeNotice ? (
    <section
      id="noah-pulse-expanded"
      className={styles.expanded}
      role="dialog"
      aria-modal={false}
      aria-label={t("pulse.expandedLabel")}
    >
      <div className={styles.expandedHeader}>
        <div className={styles.expandedIdentity}>
          <span className={styles.icon}>
            <Radio aria-hidden="true" size={15} />
          </span>
          <div>
            <strong>{t("pulse.label")}</strong>
            <small>
              {activeNotice
                ? text(activeNotice.stateLabel)
                : t("pulse.state.idle")}
            </small>
          </div>
        </div>
        <button
          ref={setCloseButtonRef}
          className={styles.closeButton}
          type="button"
          aria-label={t("pulse.close")}
          onClick={() => closePulse()}
        >
          <X aria-hidden="true" size={16} />
        </button>
      </div>

      <h2>{text(activeNotice.title)}</h2>
      <p className={styles.summary}>
        {text(activeNotice.summary)}
      </p>

      <dl className={styles.context}>
        <div>
          <dt>{t("pulse.facts")}</dt>
          <dd>
            {activeNotice.facts
              ? text(activeNotice.facts)
              : "—"}
          </dd>
        </div>
        <div>
          <dt>{t("pulse.analysis")}</dt>
          <dd>
            {activeNotice.analysis
              ? text(activeNotice.analysis)
              : "—"}
          </dd>
        </div>
        <div>
          <dt>{t("pulse.next")}</dt>
          <dd>
            {activeNotice.nextAction
              ? text(activeNotice.nextAction)
              : "—"}
          </dd>
        </div>
      </dl>

      <button
        className={styles.openAction}
        type="button"
        onClick={() => handleOpenAction()}
      >
        <span>{t("pulse.openAction")}</span>
        <ArrowUpRight aria-hidden="true" size={16} />
      </button>
      <small className={styles.scope}>{t("pulse.notice.scope")}</small>
    </section>
  ) : (
    collapsedContent
  );

  return (
    <aside className={styles.root} data-state={state}>
      <MotionMorphingSurface
        className={[
          styles.surface,
          isExpanded && activeNotice ? styles.surfaceExpanded : "",
        ]
          .filter(Boolean)
          .join(" ")}
        contentClassName={styles.surfaceContent}
        isExpanded={isExpanded && canExpand}
        collapsedContent={collapsedContent}
        expandedContent={expandedContent}
      />
    </aside>
  );
}
