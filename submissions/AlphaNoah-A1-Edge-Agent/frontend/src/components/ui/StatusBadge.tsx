import type { PropsWithChildren } from "react";

import styles from "./StatusBadge.module.css";

export type StatusTone =
  | "info"
  | "attention"
  | "warning"
  | "critical"
  | "success";

interface StatusBadgeProps extends PropsWithChildren {
  tone: StatusTone;
}

export function StatusBadge({ tone, children }: StatusBadgeProps) {
  return (
    <span className={`${styles.badge} ${styles[tone]}`}>
      <span className={styles.dot} aria-hidden="true" />
      {children}
    </span>
  );
}
