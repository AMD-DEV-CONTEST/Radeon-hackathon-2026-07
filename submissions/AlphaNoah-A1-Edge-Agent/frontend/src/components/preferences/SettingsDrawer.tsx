import { Languages, MoonStar, X } from "lucide-react";
import {
  useEffect,
  useRef,
  type MutableRefObject,
} from "react";

import { useI18n } from "../../i18n/I18nContext";
import { AiRuntimeSetupPanel } from "../../features/runtime";
import {
  usePreferences,
} from "../../preferences/PreferencesContext";
import type {
  Locale,
  MotionPreference,
  ThemePreference,
} from "../../preferences/preferences";
import { Button } from "../ui/Button";
import { GlassPanel } from "../ui/GlassPanel";
import { IconContainer } from "../ui/IconContainer";
import styles from "./SettingsDrawer.module.css";

interface SettingsDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  returnFocusRef: MutableRefObject<HTMLButtonElement | null>;
}

export function SettingsDrawer({
  isOpen,
  onClose,
  returnFocusRef,
}: SettingsDrawerProps) {
  const { t } = useI18n();
  const {
    preferences,
    setLocale,
    setTheme,
    setMotion,
  } = usePreferences();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        returnFocusRef.current?.focus();
        return;
      }

      if (event.key === "Tab") {
        const focusable = overlayRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        const first = focusable?.[0];
        const last = focusable?.[focusable.length - 1];

        if (!first || !last) {
          return;
        }

        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };

    closeButtonRef.current?.focus();
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose, returnFocusRef]);

  if (!isOpen) {
    return null;
  }

  const closeAndRestoreFocus = () => {
    onClose();
    returnFocusRef.current?.focus();
  };

  return (
    <div
      ref={overlayRef}
      className={styles.overlay}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          closeAndRestoreFocus();
        }
      }}
    >
      <GlassPanel
        level={3}
        className={styles.drawer}
        role="dialog"
        aria-modal="true"
        aria-labelledby="preferences-title"
        aria-describedby="preferences-description"
      >
        <div className={styles.header}>
          <div className={styles.heading}>
            <IconContainer tone="info">
              <Languages />
            </IconContainer>
            <div>
              <h2 id="preferences-title">{t("settings.title")}</h2>
              <p id="preferences-description">
                {t("settings.description")}
              </p>
            </div>
          </div>
          <Button
            ref={closeButtonRef}
            className={styles.closeButton}
            variant="secondary"
            aria-label={t("settings.close")}
            onClick={closeAndRestoreFocus}
          >
            <X aria-hidden="true" size={18} />
          </Button>
        </div>

        <PreferenceGroup
          name="locale"
          title={t("settings.locale.title")}
          description={t("settings.locale.description")}
          value={preferences.locale}
          options={[
            { value: "zh-CN", label: t("settings.locale.zh") },
            { value: "en-US", label: t("settings.locale.en") },
          ]}
          onChange={(value) => setLocale(value as Locale)}
        />

        <PreferenceGroup
          name="theme"
          title={t("settings.theme.title")}
          description={t("settings.theme.description")}
          value={preferences.theme}
          options={[
            { value: "system", label: t("settings.theme.system") },
            { value: "light", label: t("settings.theme.light") },
            { value: "dark", label: t("settings.theme.dark") },
          ]}
          onChange={(value) => setTheme(value as ThemePreference)}
        />

        <PreferenceGroup
          name="motion"
          title={t("settings.motion.title")}
          description={t("settings.motion.description")}
          value={preferences.motion}
          options={[
            { value: "standard", label: t("settings.motion.standard") },
            { value: "reduced", label: t("settings.motion.reduced") },
          ]}
          onChange={(value) => setMotion(value as MotionPreference)}
        />

        <AiRuntimeSetupPanel />

        <div className={styles.storageNote}>
          <MoonStar aria-hidden="true" size={16} />
          <span>{t("settings.storage.note")}</span>
        </div>
      </GlassPanel>
    </div>
  );
}

interface PreferenceOption {
  value: string;
  label: string;
}

interface PreferenceGroupProps {
  name: string;
  title: string;
  description: string;
  value: string;
  options: readonly PreferenceOption[];
  onChange: (value: string) => void;
}

function PreferenceGroup({
  name,
  title,
  description,
  value,
  options,
  onChange,
}: PreferenceGroupProps) {
  return (
    <fieldset className={styles.group}>
      <legend>{title}</legend>
      <p>{description}</p>
      <div className={styles.options}>
        {options.map((option) => (
          <label className={styles.option} key={option.value}>
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={(event) => onChange(event.target.value)}
            />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
