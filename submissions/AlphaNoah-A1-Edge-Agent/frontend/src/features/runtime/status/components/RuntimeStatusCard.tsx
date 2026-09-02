import { Cpu, RadioTower } from "lucide-react";

import { GlassPanel } from "../../../../components/ui/GlassPanel";
import { IconContainer } from "../../../../components/ui/IconContainer";
import { StatusBadge } from "../../../../components/ui/StatusBadge";
import { useI18n } from "../../../../i18n/I18nContext";
import { useProviderRuntimeStatus } from "../provider/ProviderRuntimeStatusContext";
import {
  executionKey,
  healthKey,
  presentProviderRuntime,
  providerKey,
  selectionSourceKey,
} from "./providerRuntimePresentation";
import styles from "./RuntimeStatusCard.module.css";

export function RuntimeStatusCard() {
  const { t } = useI18n();
  const resource = useProviderRuntimeStatus();
  const presentation = presentProviderRuntime(resource);
  const snapshot = presentation.snapshot;

  return (
    <GlassPanel
      level={1}
      className={styles.card}
      data-runtime-state={presentation.state}
      aria-labelledby="runtime-status-title"
    >
      <header className={styles.identity}>
        <IconContainer
          tone={presentation.state === "ready" ? "success" : "info"}
        >
          <Cpu aria-hidden="true" />
        </IconContainer>
        <div>
          <span className={styles.eyebrow}>
            {t("runtime.card.eyebrow")}
          </span>
          <h2 id="runtime-status-title">{t("runtime.card.title")}</h2>
          <p>{t(presentation.description)}</p>
        </div>
      </header>

      <div className={styles.status}>
        <StatusBadge tone={presentation.tone}>
          {t(presentation.label)}
        </StatusBadge>
        <span className={styles.source}>
          <RadioTower aria-hidden="true" size={14} />
          {t(
            resource.source === "http"
              ? "runtime.source.live"
              : "runtime.source.mock",
          )}
        </span>
      </div>

      <dl className={styles.facts}>
        <RuntimeFact
          label={t("runtime.field.provider")}
          value={snapshot ? t(providerKey(snapshot)) : t("runtime.value.unknown")}
        />
        <RuntimeFact
          label={t("runtime.field.model")}
          value={snapshot?.model ?? t("runtime.value.notReported")}
        />
        <RuntimeFact
          label={t("runtime.field.execution")}
          value={snapshot ? t(executionKey(snapshot)) : t("runtime.value.unknown")}
        />
        <RuntimeFact
          label={t("runtime.field.health")}
          value={snapshot ? t(healthKey(snapshot)) : t("runtime.value.unknown")}
        />
        <RuntimeFact
          label={t("runtime.field.configuration")}
          value={
            snapshot
              ? t(selectionSourceKey(snapshot))
              : t("runtime.value.unknown")
          }
        />
      </dl>
    </GlassPanel>
  );
}

function RuntimeFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
