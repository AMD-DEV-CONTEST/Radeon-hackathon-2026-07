import type { HTMLAttributes, PropsWithChildren } from "react";

import styles from "./GlassPanel.module.css";

export type GlassLevel = 1 | 2 | 3;

interface GlassPanelProps
  extends PropsWithChildren,
    HTMLAttributes<HTMLElement> {
  level: GlassLevel;
}

export function GlassPanel({
  level,
  children,
  className = "",
  ...props
}: GlassPanelProps) {
  const classes = [
    styles.panel,
    styles[`level${level}`],
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <section className={classes} {...props}>
      {children}
    </section>
  );
}
