import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";

import { usePreferences } from "../../preferences/PreferencesContext";
import {
  gentleSpring,
  morphContentVariants,
  reducedTransition,
} from "./motionPresets";

interface MotionMorphingSurfaceProps {
  className?: string;
  contentClassName?: string;
  isExpanded: boolean;
  collapsedContent: ReactNode;
  expandedContent: ReactNode;
}

export function MotionMorphingSurface({
  className,
  contentClassName,
  isExpanded,
  collapsedContent,
  expandedContent,
}: MotionMorphingSurfaceProps) {
  const {
    preferences: { motion: motionPreference },
  } = usePreferences();
  const reduceMotion = motionPreference === "reduced";
  const transition = reduceMotion ? reducedTransition : gentleSpring;

  return (
    <motion.div
      className={className}
      data-expanded={isExpanded}
    >
      <AnimatePresence initial={false} mode="wait">
        <motion.div
          className={contentClassName}
          key={isExpanded ? "expanded" : "collapsed"}
          initial={reduceMotion ? false : "hidden"}
          animate="visible"
          exit="exit"
          variants={morphContentVariants}
          transition={transition}
        >
          {isExpanded ? expandedContent : collapsedContent}
        </motion.div>
      </AnimatePresence>
    </motion.div>
  );
}
