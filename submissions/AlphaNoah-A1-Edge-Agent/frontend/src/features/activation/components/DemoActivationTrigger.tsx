import { AlertTriangle, RotateCw } from "lucide-react";

import { Button } from "../../../components/ui/Button";
import { useI18n } from "../../../i18n/I18nContext";
import { useActivation } from "../hooks/useActivation";
import styles from "./DemoActivationTrigger.module.css";

export function DemoActivationTrigger() {
  const { t } = useI18n();
  const { activate, error, retry, snapshot, status } =
    useActivation();
  const isActivating = status === "activating";

  return (
    <aside
      className={styles.root}
      aria-label={t("activation.demo.label")}
    >
      <div className={styles.copy}>
        <span>{t("activation.demo.label")}</span>
        <small>
          {snapshot
            ? t("activation.demo.activated")
            : t("activation.demo.description")}
        </small>
      </div>
      {error ? (
        <div className={styles.error} role="alert">
          <span>{t("activation.demo.error")}</span>
          {error.retryable ? (
            <Button
              variant="secondary"
              disabled={isActivating}
              onClick={() => void retry()}
            >
              <RotateCw aria-hidden="true" size={15} />
              {t("activation.demo.retry")}
            </Button>
          ) : null}
        </div>
      ) : (
        <Button
          className={styles.trigger}
          variant="secondary"
          disabled={isActivating || Boolean(snapshot)}
          aria-busy={isActivating}
          onClick={() => void activate()}
        >
          <AlertTriangle aria-hidden="true" size={16} />
          {t(
            isActivating
              ? "activation.demo.activating"
              : snapshot
                ? "activation.demo.active"
                : "activation.demo.trigger",
          )}
        </Button>
      )}
    </aside>
  );
}
