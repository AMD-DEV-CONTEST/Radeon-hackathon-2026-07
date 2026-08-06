import { AnimatePresence, motion } from "motion/react";
import type { PropsWithChildren } from "react";

import { usePreferences } from "../../preferences/PreferencesContext";
import {
  actionPanelVariants,
  overlayVariants,
  panelSpring,
  reducedTransition,
} from "./motionPresets";

interface MotionOverlayProps extends PropsWithChildren {
  isVisible: boolean;
  overlayClassName?: string;
  surfaceClassName?: string;
  labelledBy: string;
  describedBy?: string;
  onBackdropMouseDown: () => void;
}

export function MotionOverlay({
  isVisible,
  overlayClassName,
  surfaceClassName,
  labelledBy,
  describedBy,
  onBackdropMouseDown,
  children,
}: MotionOverlayProps) {
  const {
    preferences: { motion: motionPreference },
  } = usePreferences();
  const reduceMotion = motionPreference === "reduced";
  const transition = reduceMotion ? reducedTransition : panelSpring;

  return (
    <AnimatePresence>
      {isVisible ? (
        <motion.div
          className={overlayClassName}
          initial={reduceMotion ? false : "hidden"}
          animate="visible"
          exit="exit"
          variants={overlayVariants}
          transition={transition}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              onBackdropMouseDown();
            }
          }}
        >
          <motion.aside
            className={surfaceClassName}
            role="dialog"
            aria-modal="true"
            aria-labelledby={labelledBy}
            aria-describedby={describedBy}
            initial={reduceMotion ? false : "hidden"}
            animate="visible"
            exit="exit"
            variants={actionPanelVariants}
            transition={transition}
          >
            {children}
          </motion.aside>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
