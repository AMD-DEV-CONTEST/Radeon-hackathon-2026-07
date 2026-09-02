import {
  forwardRef,
  type ButtonHTMLAttributes,
  type PropsWithChildren,
} from "react";

import styles from "./Button.module.css";

export type ButtonVariant = "primary" | "secondary" | "danger";

interface ButtonProps
  extends PropsWithChildren,
    ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = "primary",
      children,
      className = "",
      type = "button",
      ...props
    },
    ref,
  ) {
    const classes = [styles.button, styles[variant], className]
      .filter(Boolean)
      .join(" ");

    return (
      <button ref={ref} className={classes} type={type} {...props}>
        {children}
      </button>
    );
  },
);
