import { useI18n } from "../../../i18n/I18nContext";
import type { DataQuality } from "../../runtime";
import styles from "./DigitalEmployees.module.css";

interface DataQualityNoticeProps {
  quality: DataQuality;
}

export function DataQualityNotice({
  quality,
}: DataQualityNoticeProps) {
  const { t } = useI18n();

  if (quality.availability === "available") {
    return null;
  }

  return (
    <p className={styles.qualityNotice} role="status">
      {quality.availability === "partial"
        ? t("employees.quality.partial")
        : t("employees.quality.unavailable")}
    </p>
  );
}
