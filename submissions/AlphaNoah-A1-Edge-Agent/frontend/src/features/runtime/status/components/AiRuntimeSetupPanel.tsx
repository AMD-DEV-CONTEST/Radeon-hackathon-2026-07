import {
  Cloud,
  Cpu,
  HardDrive,
  RefreshCw,
  Sparkles,
} from "lucide-react";

import { Button } from "../../../../components/ui/Button";
import { StatusBadge } from "../../../../components/ui/StatusBadge";
import { useI18n } from "../../../../i18n/I18nContext";
import { useProviderRuntimeStatus } from "../provider/ProviderRuntimeStatusContext";
import {
  executionKey,
  presentProviderRuntime,
  providerKey,
} from "./providerRuntimePresentation";
import styles from "./AiRuntimeSetupPanel.module.css";

export function AiRuntimeSetupPanel() {
  const { t } = useI18n();
  const resource = useProviderRuntimeStatus();
  const presentation = presentProviderRuntime(resource);
  const snapshot = presentation.snapshot;
  const isRefreshing =
    resource.status === "loading" || resource.status === "refreshing";

  const localRuntimeValue =
    snapshot?.execution === "local" && snapshot.provider
      ? t(providerKey(snapshot))
      : snapshot
        ? t("runtime.setup.notSelected")
        : t("runtime.value.unknown");
  const cloudRuntimeValue =
    snapshot?.execution === "remote" && snapshot.provider
      ? t(providerKey(snapshot))
      : snapshot
        ? t("runtime.setup.notSelected")
        : t("runtime.value.unknown");
  const currentSelection = snapshot
    ? `${t(providerKey(snapshot))} · ${
        snapshot.model ?? t("runtime.value.notReported")
      } · ${t(executionKey(snapshot))}`
    : t("runtime.value.unknown");

  return (
    <section
      className={styles.panel}
      aria-labelledby="ai-runtime-setup-title"
    >
      <header className={styles.header}>
        <div>
          <span className={styles.icon} aria-hidden="true">
            <Sparkles />
          </span>
          <div>
            <h3 id="ai-runtime-setup-title">
              {t("runtime.setup.title")}
            </h3>
            <p>{t("runtime.setup.description")}</p>
          </div>
        </div>
        <StatusBadge tone={presentation.tone}>
          {t(presentation.label)}
        </StatusBadge>
      </header>

      <h4>{t("runtime.setup.environmentCheck")}</h4>
      <dl className={styles.checks}>
        <EnvironmentRow
          icon={<Cpu />}
          label={t("runtime.setup.amdGpu")}
          value={t("runtime.setup.notReported")}
        />
        <EnvironmentRow
          icon={<HardDrive />}
          label={t("runtime.setup.localRuntime")}
          value={localRuntimeValue}
        />
        <EnvironmentRow
          icon={<Cloud />}
          label={t("runtime.setup.cloudProvider")}
          value={cloudRuntimeValue}
        />
      </dl>

      <div className={styles.selection}>
        <span>{t("runtime.setup.currentSelection")}</span>
        <strong>{currentSelection}</strong>
      </div>

      <Button
        className={styles.refresh}
        variant="secondary"
        disabled={isRefreshing}
        onClick={resource.refresh}
      >
        <RefreshCw aria-hidden="true" size={16} />
        {t(
          isRefreshing
            ? "runtime.setup.refreshing"
            : "runtime.setup.refresh",
        )}
      </Button>

      <p className={styles.boundary}>{t("runtime.setup.boundary")}</p>
    </section>
  );
}

function EnvironmentRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div>
      <dt>
        <span aria-hidden="true">{icon}</span>
        {label}
      </dt>
      <dd>{value}</dd>
    </div>
  );
}
