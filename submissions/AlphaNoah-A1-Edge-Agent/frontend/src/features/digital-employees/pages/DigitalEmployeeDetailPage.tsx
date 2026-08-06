import {
  ArrowLeft,
  BookOpen,
  BriefcaseBusiness,
  ListChecks,
  ShieldCheck,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { MotionWrapper } from "../../../components/motion/MotionWrapper";
import { Button } from "../../../components/ui/Button";
import { GlassPanel } from "../../../components/ui/GlassPanel";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { useI18n } from "../../../i18n/I18nContext";
import { CapabilityModuleList } from "../components/CapabilityModuleList";
import { DataQualityNotice } from "../components/DataQualityNotice";
import { EmployeeIdentity } from "../components/EmployeeIdentity";
import { WorkRecordList } from "../components/WorkRecordList";
import { formatEmployeeTime } from "../components/employeeTime";
import { useDigitalEmployee } from "../provider/useDigitalEmployee";
import styles from "../components/DigitalEmployees.module.css";

export function DigitalEmployeeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { locale, t, text } = useI18n();
  const {
    collection,
    employee,
    error,
    refresh,
    source,
    status,
  } = useDigitalEmployee(id);
  const isInitialLoading =
    !collection && (status === "idle" || status === "loading");

  if (isInitialLoading) {
    return (
      <DetailResourceState
        title={t("employees.state.loading")}
        description={t("employees.state.loadingDescription")}
      />
    );
  }

  if (!collection && status === "error") {
    return (
      <DetailResourceState
        title={t("employees.state.error")}
        description={t("employees.state.errorDescription")}
        retryLabel={t("employees.state.retry")}
        onRetry={refresh}
      />
    );
  }

  if (collection && !employee) {
    return (
      <section
        className={styles.page}
        aria-labelledby="employee-not-found-title"
      >
        <Link className={styles.backLink} to="/employees">
          <ArrowLeft aria-hidden="true" size={16} />
          {t("employees.detail.back")}
        </Link>
        <GlassPanel level={2} className={styles.notFound}>
          <p>{t("employees.detail.eyebrow")}</p>
          <h1 id="employee-not-found-title">
            {t("employees.notFound.title")}
          </h1>
          <span>{t("employees.notFound.description")}</span>
        </GlassPanel>
      </section>
    );
  }

  if (!employee) {
    return null;
  }

  const metrics = employee.todayMetrics;

  return (
    <section
      className={styles.page}
      aria-labelledby="employee-detail-title"
    >
      <MotionWrapper order={0}>
        <Link className={styles.backLink} to="/employees">
          <ArrowLeft aria-hidden="true" size={16} />
          {t("employees.detail.back")}
        </Link>
      </MotionWrapper>

      {error && collection ? (
        <div className={styles.staleNotice} role="status">
          <span>{t("employees.state.stale")}</span>
          <Button variant="secondary" onClick={refresh}>
            {t("employees.state.retry")}
          </Button>
        </div>
      ) : null}

      <DataQualityNotice quality={employee.quality} />

      <MotionWrapper order={1}>
        <EmployeeIdentity employee={employee} />
      </MotionWrapper>

      <MotionWrapper order={2}>
        <GlassPanel level={2} className={styles.detailSurface}>
          <div className={styles.overviewStrip}>
            <div>
              <span>{t("employees.metrics.handled")}</span>
              <strong>
                {metrics.handled ??
                  (metrics.quality.availability === "unavailable"
                    ? t("employees.value.unavailable")
                    : t("employees.value.unknown"))}
              </strong>
            </div>
            <div>
              <span>{t("employees.metrics.pending")}</span>
              <strong>
                {metrics.pending ??
                  (metrics.quality.availability === "unavailable"
                    ? t("employees.value.unavailable")
                    : t("employees.value.unknown"))}
              </strong>
            </div>
            <div>
              <span>{t("employees.source.label")}</span>
              <strong>
                {source === "mock"
                  ? t("employees.source.mock")
                  : t("employees.source.http")}
              </strong>
              {collection?.observedAt ? (
                <time dateTime={collection.observedAt}>
                  {formatEmployeeTime(
                    collection.observedAt,
                    locale,
                    true,
                  )}
                </time>
              ) : null}
            </div>
          </div>
          <DataQualityNotice quality={metrics.quality} />

          <section
            className={styles.detailSection}
            aria-labelledby="employee-responsibilities"
          >
            <div className={styles.sectionHeading}>
              <BriefcaseBusiness aria-hidden="true" />
              <div>
                <h2 id="employee-responsibilities">
                  {t("employees.responsibilities")}
                </h2>
                <p>
                  {t("employees.responsibilities.description")}
                </p>
              </div>
            </div>
            {employee.responsibilities.length ? (
              <ul className={styles.responsibilityList}>
                {employee.responsibilities.map((responsibility) => (
                  <li key={responsibility.id}>
                    <strong>{text(responsibility.label)}</strong>
                    {responsibility.scope ? (
                      <p>{text(responsibility.scope)}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.emptyInline}>
                {t("employees.responsibilities.empty")}
              </p>
            )}
          </section>

          <CapabilityModuleList modules={employee.skills} />

          <section
            className={styles.detailSection}
            aria-labelledby="employee-current-tasks"
          >
            <div className={styles.sectionHeading}>
              <ListChecks aria-hidden="true" />
              <div>
                <h2 id="employee-current-tasks">
                  {t("employees.tasks")}
                </h2>
                <p>{t("employees.tasks.description")}</p>
              </div>
            </div>
            {employee.currentEventId ? (
              <p className={styles.currentEvent}>
                <span>{t("employees.currentEvent")}</span>
                <code>{employee.currentEventId}</code>
              </p>
            ) : null}
            {employee.currentTasks.length ? (
              <ul className={styles.taskList}>
                {employee.currentTasks.map((task) => (
                  <li key={task.id}>
                    <div>
                      <strong>{text(task.title)}</strong>
                      {task.updatedAt ? (
                        <time dateTime={task.updatedAt}>
                          {t("employees.updated")}
                          {" · "}
                          {formatEmployeeTime(
                            task.updatedAt,
                            locale,
                          )}
                        </time>
                      ) : null}
                    </div>
                    <StatusBadge tone={task.statusTone}>
                      {text(task.statusLabel)}
                    </StatusBadge>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.emptyInline}>
                {t("employees.tasks.empty")}
              </p>
            )}
          </section>

          <WorkRecordList records={employee.workRecords} />

          <div className={styles.secondarySections}>
            <section
              className={styles.detailSection}
              aria-labelledby="employee-knowledge"
            >
              <div className={styles.sectionHeading}>
                <BookOpen aria-hidden="true" />
                <div>
                  <h2 id="employee-knowledge">
                    {t("employees.knowledge")}
                  </h2>
                  <p>{t("employees.knowledge.description")}</p>
                </div>
              </div>
              {employee.knowledge.length ? (
                <ul className={styles.simpleList}>
                  {employee.knowledge.map((scope) => (
                    <li key={scope.id}>{text(scope.label)}</li>
                  ))}
                </ul>
              ) : (
                <p className={styles.emptyInline}>
                  {t("employees.knowledge.empty")}
                </p>
              )}
            </section>

            <section
              className={styles.detailSection}
              aria-labelledby="employee-boundary"
            >
              <div className={styles.sectionHeading}>
                <ShieldCheck aria-hidden="true" />
                <div>
                  <h2 id="employee-boundary">
                    {t("employees.boundary")}
                  </h2>
                  <p>{t("employees.boundary.description")}</p>
                </div>
              </div>
              <strong className={styles.boundaryLabel}>
                {text(employee.permissionSummary.label)}
              </strong>
              {employee.permissionSummary.constraints.length ? (
                <ul className={styles.simpleList}>
                  {employee.permissionSummary.constraints.map(
                    (constraint, index) => (
                      <li key={index}>{text(constraint)}</li>
                    ),
                  )}
                </ul>
              ) : (
                <p className={styles.emptyInline}>
                  {t("employees.boundary.empty")}
                </p>
              )}
              <p className={styles.nonAuthoritative}>
                {t("employees.boundary.nonAuthoritative")}
              </p>
            </section>
          </div>
        </GlassPanel>
      </MotionWrapper>
    </section>
  );
}

function DetailResourceState({
  title,
  description,
  retryLabel,
  onRetry,
}: {
  title: string;
  description: string;
  retryLabel?: string;
  onRetry?: () => void;
}) {
  const { t } = useI18n();
  return (
    <section
      className={styles.page}
      aria-labelledby="employee-detail-state"
    >
      <Link className={styles.backLink} to="/employees">
        <ArrowLeft aria-hidden="true" size={16} />
        {t("employees.detail.back")}
      </Link>
      <GlassPanel level={2} className={styles.notFound}>
        <h1 id="employee-detail-state">{title}</h1>
        <span>{description}</span>
        {retryLabel && onRetry ? (
          <Button variant="secondary" onClick={onRetry}>
            {retryLabel}
          </Button>
        ) : null}
      </GlassPanel>
    </section>
  );
}
