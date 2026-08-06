import {
  BookOpen,
  Check,
  ClipboardCheck,
  FileSearch,
  Search,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import type { ComponentType } from "react";

import { useI18n } from "../../../i18n/I18nContext";
import type { WorkRecord, WorkRecordKind } from "../types";
import styles from "./DigitalEmployees.module.css";

interface WorkRecordListProps {
  records: readonly WorkRecord[];
}

const recordIcons: Record<
  WorkRecordKind,
  ComponentType<{ "aria-hidden"?: "true" }>
> = {
  event_detected: Search,
  analysis: FileSearch,
  knowledge_lookup: BookOpen,
  human_review: ShieldCheck,
  task: Wrench,
  evidence: ClipboardCheck,
  completed: Check,
  unknown: Search,
};

export function WorkRecordList({
  records,
}: WorkRecordListProps) {
  const { t, text } = useI18n();

  return (
    <section
      className={styles.detailSection}
      aria-labelledby="employee-work-records"
    >
      <div className={styles.sectionHeading}>
        <ClipboardCheck aria-hidden="true" />
        <div>
          <h2 id="employee-work-records">
            {t("employees.records")}
          </h2>
          <p>{t("employees.records.description")}</p>
        </div>
      </div>
      {records.length ? (
        <ol className={styles.recordList}>
          {records.map((record) => {
            const RecordIcon = recordIcons[record.kind];
            return (
              <li key={record.id} className={styles.recordItem}>
                <span
                  className={styles.recordMarker}
                  aria-hidden="true"
                >
                  <RecordIcon aria-hidden="true" />
                </span>
                <div className={styles.recordTime}>
                  {record.occurredAt ? (
                    <time dateTime={record.occurredAt}>
                      {record.occurredLabel
                        ? text(record.occurredLabel)
                        : record.occurredAt}
                    </time>
                  ) : (
                    t("employees.value.unknown")
                  )}
                </div>
                <div className={styles.recordCopy}>
                  <strong>{text(record.title)}</strong>
                  {record.detail ? (
                    <p>{text(record.detail)}</p>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className={styles.emptyInline}>
          {t("employees.records.empty")}
        </p>
      )}
    </section>
  );
}
