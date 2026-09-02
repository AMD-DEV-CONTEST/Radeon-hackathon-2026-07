import { StatusBadge } from "../../../components/ui/StatusBadge";
import { useI18n } from "../../../i18n/I18nContext";
import type { DigitalEmployeeView } from "../types";
import styles from "./DigitalEmployees.module.css";

interface EmployeeStateProps {
  employee: DigitalEmployeeView;
  compact?: boolean;
}

export function EmployeeState({
  employee,
  compact = false,
}: EmployeeStateProps) {
  const { text } = useI18n();

  return (
    <div
      className={styles.employeeState}
      data-compact={compact ? "true" : "false"}
    >
      <StatusBadge tone={employee.statusTone}>
        {text(employee.statusLabel)}
      </StatusBadge>
      <StatusBadge tone={employee.stageTone}>
        {text(employee.stageLabel)}
      </StatusBadge>
    </div>
  );
}
