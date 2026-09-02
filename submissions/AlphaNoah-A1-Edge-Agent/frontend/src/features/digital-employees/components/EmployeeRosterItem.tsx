import { ArrowUpRight, Bot } from "lucide-react";
import { Link } from "react-router-dom";

import { IconContainer } from "../../../components/ui/IconContainer";
import { useI18n } from "../../../i18n/I18nContext";
import type { DigitalEmployeeView } from "../types";
import styles from "./DigitalEmployees.module.css";
import { EmployeeState } from "./EmployeeState";
import { formatEmployeeTime } from "./employeeTime";

interface EmployeeRosterItemProps {
  employee: DigitalEmployeeView;
}

export function EmployeeRosterItem({
  employee,
}: EmployeeRosterItemProps) {
  const { locale, t, text } = useI18n();
  const handled = employee.todayMetrics.handled;
  const pending = employee.todayMetrics.pending;

  return (
    <li className={styles.rosterListItem}>
      <Link
        className={styles.rosterItem}
        to={`/employees/${encodeURIComponent(employee.id)}`}
      >
        <span className={styles.rosterIdentity}>
          <IconContainer
            size="md"
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
          <span>
            <strong>{text(employee.name)}</strong>
            {employee.description ? (
              <span>{text(employee.description)}</span>
            ) : null}
          </span>
        </span>

        <span className={styles.rosterState}>
          <EmployeeState employee={employee} compact />
          {employee.statusObservedAt ? (
            <span className={styles.observedTime}>
              {t("employees.observed")}
              {" · "}
              <time dateTime={employee.statusObservedAt}>
                {formatEmployeeTime(
                  employee.statusObservedAt,
                  locale,
                )}
              </time>
            </span>
          ) : (
            <span className={styles.observedTime}>
              {t("employees.value.unknown")}
            </span>
          )}
        </span>

        <span className={styles.rosterResponsibilities}>
          <span className={styles.columnLabel}>
            {t("employees.responsibilities")}
          </span>
          <span>
            {employee.responsibilities.length
              ? employee.responsibilities
                  .slice(0, 2)
                  .map((responsibility) => text(responsibility.label))
                  .join(" · ")
              : t("employees.responsibilities.empty")}
          </span>
        </span>

        <span className={styles.rosterMetrics}>
          <span className={styles.metric}>
            <span>{t("employees.metrics.handled")}</span>
            <strong>
              {handled ??
                (employee.todayMetrics.quality.availability ===
                "unavailable"
                  ? t("employees.value.unavailable")
                  : t("employees.value.unknown"))}
            </strong>
          </span>
          <span className={styles.metric}>
            <span>{t("employees.metrics.pending")}</span>
            <strong>
              {pending ??
                (employee.todayMetrics.quality.availability ===
                "unavailable"
                  ? t("employees.value.unavailable")
                  : t("employees.value.unknown"))}
            </strong>
          </span>
        </span>

        <ArrowUpRight
          className={styles.rosterArrow}
          aria-hidden="true"
          size={18}
        />
      </Link>
    </li>
  );
}
