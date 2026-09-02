import { Blocks } from "lucide-react";

import { StatusBadge } from "../../../components/ui/StatusBadge";
import { useI18n } from "../../../i18n/I18nContext";
import type { CapabilityModule } from "../types";
import styles from "./DigitalEmployees.module.css";

interface CapabilityModuleListProps {
  modules: readonly CapabilityModule[];
}

export function CapabilityModuleList({
  modules,
}: CapabilityModuleListProps) {
  const { t, text } = useI18n();

  return (
    <section
      className={styles.detailSection}
      aria-labelledby="employee-capabilities"
    >
      <div className={styles.sectionHeading}>
        <Blocks aria-hidden="true" />
        <div>
          <h2 id="employee-capabilities">
            {t("employees.capabilities")}
          </h2>
          <p>{t("employees.capabilities.description")}</p>
        </div>
      </div>
      {modules.length ? (
        <ul className={styles.capabilityList}>
          {modules.map((module) => (
            <li key={module.id} className={styles.capabilityItem}>
              <div>
                <strong>{text(module.name)}</strong>
                {module.description ? (
                  <p>{text(module.description)}</p>
                ) : null}
              </div>
              <StatusBadge tone={module.availabilityTone}>
                {text(module.availabilityLabel)}
              </StatusBadge>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.emptyInline}>
          {t("employees.capabilities.empty")}
        </p>
      )}
    </section>
  );
}
