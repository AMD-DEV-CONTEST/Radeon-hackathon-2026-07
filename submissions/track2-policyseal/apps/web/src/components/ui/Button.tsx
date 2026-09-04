import { Slot } from "@radix-ui/react-slot";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "../../lib/utils";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  asChild?: boolean;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "default" | "small" | "icon";
  icon?: ReactNode;
}

export function Button({
  asChild,
  variant = "secondary",
  size = "default",
  icon,
  className,
  children,
  ...props
}: ButtonProps) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      className={cn("button", `button--${variant}`, `button--${size}`, className)}
      {...props}
    >
      {icon ? <span className="button__icon">{icon}</span> : null}
      {children}
    </Component>
  );
}
