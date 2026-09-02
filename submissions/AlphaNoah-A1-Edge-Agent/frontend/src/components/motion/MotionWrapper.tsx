import { motion } from "motion/react";
import type { PropsWithChildren } from "react";

import { usePreferences } from "../../preferences/PreferencesContext";
import {
  motionPresets,
  motionTransition,
  reducedTransition,
  type MotionPreset,
} from "./motionPresets";

interface MotionWrapperProps extends PropsWithChildren {
  className?: string;
  preset?: MotionPreset;
  order?: number;
}

export function MotionWrapper({
  children,
  className,
  preset = "rise",
  order = 0,
}: MotionWrapperProps) {
  const {
    preferences: { motion: motionPreference },
  } = usePreferences();
  const reduceMotion = motionPreference === "reduced";

  return (
    <motion.div
      className={className}
      initial={reduceMotion ? false : "hidden"}
      animate="visible"
      variants={motionPresets[preset]}
      transition={
        reduceMotion ? reducedTransition : motionTransition(order)
      }
    >
      {children}
    </motion.div>
  );
}
