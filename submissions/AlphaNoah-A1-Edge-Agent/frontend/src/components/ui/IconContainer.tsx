import type { PropsWithChildren } from "react";

import styles from "./IconContainer.module.css";

type IconTone =
  | "neutral"
  | "info"
  | "attention"
  | "critical"
  | "success";

type IconSize = "sm" | "md" | "lg";

interface IconContainerProps extends PropsWithChildren {
  tone?: IconTone;
  size?: IconSize;
  label?: string;
}

export function IconContainer({
  tone = "neutral",
  size = "md",
  label,
  children,
}: IconContainerProps) {
  return (
    <span
      className={`${styles.container} ${styles[tone]} ${styles[size]}`}
      aria-label={label}
      aria-hidden={label ? undefined : "true"}
      role={label ? "img" : undefined}
    >
      {children}
    </span>
  );
}
