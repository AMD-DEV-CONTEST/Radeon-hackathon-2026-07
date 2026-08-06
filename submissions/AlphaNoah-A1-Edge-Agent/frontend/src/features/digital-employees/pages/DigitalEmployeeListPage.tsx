import { UsersRound } from "lucide-react";

import { MotionWrapper } from "../../../components/motion/MotionWrapper";
import { Button } from "../../../components/ui/Button";
import { GlassPanel } from "../../../components/ui/GlassPanel";
import { IconContainer } from "../../../components/ui/IconContainer";
import { useI18n } from "../../../i18n/I18nContext";
import { DataQualityNotice } from "../components/DataQualityNotice";
import { EmployeeRosterItem } from "../components/EmployeeRosterItem";
import { formatEmployeeTime } from "../components/employeeTime";
import { useDigitalEmployees } from "../provider/useDigitalEmployees";
import styles from "../components/DigitalEmployees.module.css";

export function DigitalEmployeeListPage() {
  const { locale, t } = useI18n();
  const {
    collection,
    employees,
    error,
    refresh,
    source,
    status,
  } = useDigitalEmployees();
  const isInitialLoading =
    !collection && (status === "idle" || status === "loading");

  return (
    <section
      className={styles.page}
      aria-labelledby="digital-employees-title"
    >
      <MotionWrapper className={styles.pageIntro} order={0}>
        <div>
          <p>{t("employees.eyebrow")}</p>
          <h1 id="digital-employees-title">
            {t("employees.title")}
          </h1>
          <span>{t("employees.description")}</span>
        </div>
        <div className={styles.sourceMeta}>
          <span>
            {source === "mock"
              ? t("employees.source.mock")
              : t("employees.source.http")}
          </span>
          {collection?.observedAt ? (
            <span>
              {t("employees.snapshot")}
              {" · "}
              <time dateTime={collection.observedAt}>
                {formatEmployeeTime(
                  collection.observedAt,
                  locale,
                  true,
                )}
              </time>
            </span>
          ) : (
            <span>{t("employees.snapshot.unavailable")}</span>
          )}
        </div>
      </MotionWrapper>

      {error && collection ? (
        <div className={styles.staleNotice} role="status">
          <span>{t("employees.state.stale")}</span>
          <Button variant="secondary" onClick={refresh}>
            {t("employees.state.retry")}
          </Button>
        </div>
      ) : null}

      {collection ? (
        <DataQualityNotice quality={collection.quality} />
      ) : null}

      <MotionWrapper order={1}>
        <GlassPanel
          level={2}
          className={styles.rosterPanel}
          aria-labelledby="employee-roster-title"
        >
          <header className={styles.rosterHeader}>
            <div>
              <IconContainer size="sm" tone="info">
                <UsersRound aria-hidden="true" />
              </IconContainer>
              <div>
                <h2 id="employee-roster-title">
                  {t("employees.list.title")}
                </h2>
                <p>{t("employees.list.description")}</p>
              </div>
            </div>
            {collection ? (
              <span>
                {employees.length} {t("employees.list.count")}
              </span>
            ) : null}
          </header>

          {isInitialLoading ? (
            <div className={styles.resourceState} role="status">
              <strong>{t("employees.state.loading")}</strong>
              <p>{t("employees.state.loadingDescription")}</p>
            </div>
          ) : null}

          {!collection && status === "error" ? (
            <div className={styles.resourceState} role="alert">
              <strong>{t("employees.state.error")}</strong>
              <p>{t("employees.state.errorDescription")}</p>
              <Button variant="secondary" onClick={refresh}>
                {t("employees.state.retry")}
              </Button>
            </div>
          ) : null}

          {collection && employees.length === 0 ? (
            <div className={styles.resourceState}>
              <strong>{t("employees.state.empty")}</strong>
              <p>{t("employees.state.emptyDescription")}</p>
            </div>
          ) : null}

          {employees.length ? (
            <ul className={styles.rosterList}>
              {employees.map((employee) => (
                <EmployeeRosterItem
                  key={employee.id}
                  employee={employee}
                />
              ))}
            </ul>
          ) : null}
        </GlassPanel>
      </MotionWrapper>
    </section>
  );
}
