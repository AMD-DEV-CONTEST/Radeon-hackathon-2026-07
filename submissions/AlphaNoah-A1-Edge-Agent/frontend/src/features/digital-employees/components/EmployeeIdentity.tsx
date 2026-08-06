import { Bot } from "lucide-react";

import { IconContainer } from "../../../components/ui/IconContainer";
import { useI18n } from "../../../i18n/I18nContext";
import type { DigitalEmployeeView } from "../types";
import styles from "./DigitalEmployees.module.css";
import { EmployeeState } from "./EmployeeState";
import { formatEmployeeTime } from "./employeeTime";

interface EmployeeIdentityProps {
  employee: DigitalEmployeeView;
}

export function EmployeeIdentity({
  employee,
}: EmployeeIdentityProps) {
  const { locale, t, text } = useI18n();

  return (
    <header className={styles.detailIdentity}>
      <IconContainer
        size="lg"
        tone={
          employee.status === "online"
            ? "success"
            : employee.status === "working"
              ? "attention"
              : "neutral"
        }
      >
        <Bot aria-hidden="true" />
      </IconContainer>
      <div className={styles.detailIdentityCopy}>
        <p>{t("employees.detail.eyebrow")}</p>
        <h1 id="employee-detail-title">{text(employee.name)}</h1>
        {employee.description ? (
          <span>{text(employee.description)}</span>
        ) : null}
      </div>
      <div className={styles.detailIdentityState}>
        <EmployeeState employee={employee} />
        <span className={styles.observedTime}>
          {employee.statusObservedAt ? (
            <>
              {t("employees.observed")}
              {" · "}
              <time dateTime={employee.statusObservedAt}>
                {formatEmployeeTime(
                  employee.statusObservedAt,
                  locale,
                  true,
                )}
              </time>
            </>
          ) : (
            t("employees.value.unknown")
          )}
        </span>
      </div>
    </header>
  );
}
