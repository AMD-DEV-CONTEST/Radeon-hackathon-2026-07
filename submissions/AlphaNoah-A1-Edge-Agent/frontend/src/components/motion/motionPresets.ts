import type { Transition, Variants } from "motion/react";

export type MotionPreset = "fade" | "rise" | "scale";

const easing = [0.22, 1, 0.36, 1] as const;

export const motionPresets: Record<MotionPreset, Variants> = {
  fade: {
    hidden: { opacity: 0 },
    visible: { opacity: 1 },
  },
  rise: {
    hidden: { opacity: 0, y: 10 },
    visible: { opacity: 1, y: 0 },
  },
  scale: {
    hidden: { opacity: 0, scale: 0.96 },
    visible: { opacity: 1, scale: 1 },
  },
};

export function motionTransition(order: number): Transition {
  return {
    duration: 0.38,
    delay: Math.max(0, order) * 0.04,
    ease: easing,
  };
}

export const gentleSpring: Transition = {
  type: "spring",
  stiffness: 330,
  damping: 32,
  mass: 0.88,
};

export const panelSpring: Transition = {
  type: "spring",
  stiffness: 320,
  damping: 32,
  mass: 0.9,
};

export const reducedTransition: Transition = {
  duration: 0,
};

export const morphContentVariants: Variants = {
  hidden: { opacity: 0, scale: 0.985 },
  visible: { opacity: 1, scale: 1 },
  exit: { opacity: 0, scale: 0.99 },
};

export const overlayVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1 },
  exit: { opacity: 0 },
};

export const actionPanelVariants: Variants = {
  hidden: { opacity: 0, x: 36, scale: 0.985 },
  visible: { opacity: 1, x: 0, scale: 1 },
  exit: { opacity: 0, x: 24, scale: 0.99 },
};
