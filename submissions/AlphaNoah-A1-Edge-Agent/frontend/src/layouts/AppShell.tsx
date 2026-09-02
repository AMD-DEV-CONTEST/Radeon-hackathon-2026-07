import {
  Hexagon,
  PanelsTopLeft,
  Settings2,
  UsersRound,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { SettingsDrawer } from "../components/preferences/SettingsDrawer";
import { NoahPulse } from "../components/pulse/NoahPulse";
import { Button } from "../components/ui/Button";
import { IconContainer } from "../components/ui/IconContainer";
import { AgentActionPanel } from "../components/workspace/AgentActionPanel";
import { useOptionalDigitalEmployeeContext } from "../features/digital-employees";
import {
  useActionSummary,
  useEvents,
  usePulse,
  useWorkspace,
} from "../features/runtime";
import { useI18n } from "../i18n/I18nContext";
import type { TranslationKey } from "../i18n/messages";
import styles from "./AppShell.module.css";

export interface WorkspaceOutletContext {
  selectedEventId: string | null;
  openActionPanel: (
    eventId: string,
    trigger?: HTMLElement,
  ) => void;
}

export function AppShell() {
  const { t } = useI18n();
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isActionPanelOpen, setIsActionPanelOpen] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<
    string | null
  >(null);
  const workspace = useWorkspace();
  const { pathname } = useLocation();
  const previousPathnameRef = useRef(pathname);
  const employeeResource = useOptionalDigitalEmployeeContext();
  const {
    events,
    selectedEvent,
  } = useEvents(selectedEventId);
  const eventForPanel =
    selectedEventId === null ? (events[0] ?? null) : selectedEvent;
  const actionForPanel = useActionSummary(
    eventForPanel?.id ?? null,
    eventForPanel?.actionSummaryId ?? null,
  );
  const {
    currentNotice,
    status: pulseStatus,
    refresh: refreshPulse,
  } = usePulse();
  const linkedEmployee = employeeResource?.data?.employees.find(
    (employee) => employee.currentEventId === eventForPanel?.id,
  );
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const actionTriggerRef = useRef<HTMLElement | null>(null);
  const closeSettings = useCallback(() => setIsSettingsOpen(false), []);
  const openActionPanel = useCallback(
    (eventId: string, trigger?: HTMLElement) => {
      setSelectedEventId(eventId);
      actionTriggerRef.current = trigger ?? null;
      setIsActionPanelOpen(true);
    },
    [],
  );
  const closeActionPanel = useCallback(() => {
    setIsActionPanelOpen(false);
    window.requestAnimationFrame(() => actionTriggerRef.current?.focus());
  }, []);
  const refreshRuntimeProjections = useCallback(() => {
    workspace.refresh();
    refreshPulse();
    employeeResource?.refresh();
  }, [employeeResource, refreshPulse, workspace]);

  useEffect(() => {
    if (previousPathnameRef.current === pathname) {
      return;
    }
    previousPathnameRef.current = pathname;
    refreshRuntimeProjections();
  }, [pathname, refreshRuntimeProjections]);

  useEffect(() => {
    if (
      isActionPanelOpen &&
      selectedEventId !== null &&
      selectedEvent === null
    ) {
      setIsActionPanelOpen(false);
      setSelectedEventId(null);
      window.requestAnimationFrame(() =>
        actionTriggerRef.current?.focus(),
      );
    }
  }, [isActionPanelOpen, selectedEvent, selectedEventId]);

  const boundaryCopy = getBoundaryCopy(workspace.source, workspace.status);
  const outletContext: WorkspaceOutletContext = {
    selectedEventId,
    openActionPanel,
  };

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.brandCluster}>
          <div className={styles.brand}>
            <IconContainer
              size="md"
              tone="info"
              label={t("brand.mark")}
            >
              <Hexagon strokeWidth={1.8} />
            </IconContainer>
            <div>
              <p className={styles.brandName}>{t("brand.name")}</p>
              <p className={styles.brandMeta}>{t("brand.product")}</p>
            </div>
          </div>
          <span className={styles.headerDivider} aria-hidden="true" />
          <nav
            className={styles.primaryNav}
            aria-label={t("nav.primary")}
          >
            <NavLink
              className={({ isActive }) =>
                `${styles.navLink} ${
                  isActive ? styles.navLinkActive : ""
                }`
              }
              to="/"
              end
            >
              <PanelsTopLeft aria-hidden="true" />
              <span className={styles.navLabel}>
                {t("nav.workspace")}
              </span>
            </NavLink>
            <NavLink
              className={({ isActive }) =>
                `${styles.navLink} ${isActive ? styles.navLinkActive : ""}`
              }
              to="/events"
            >
              <PanelsTopLeft aria-hidden="true" />
              <span className={styles.navLabel}>Events</span>
            </NavLink>
            <NavLink
              className={({ isActive }) =>
                `${styles.navLink} ${isActive ? styles.navLinkActive : ""}`
              }
              to="/tasks"
            >
              <PanelsTopLeft aria-hidden="true" />
              <span className={styles.navLabel}>Tasks</span>
            </NavLink>
            <NavLink
              className={({ isActive }) =>
                `${styles.navLink} ${
                  isActive ? styles.navLinkActive : ""
                }`
              }
              to="/employees"
            >
              <UsersRound aria-hidden="true" />
              <span className={styles.navLabel}>
                {t("nav.employees")}
              </span>
            </NavLink>
          </nav>
        </div>

        <div className={styles.headerEnd}>
          <div
            className={styles.headerState}
            data-state={boundaryCopy.state}
            aria-label={t("shell.runtime.label")}
          >
            <span className={styles.stateDot} aria-hidden="true" />
            <span>{t(boundaryCopy.header)}</span>
          </div>
          <Button
            ref={settingsButtonRef}
            className={styles.settingsButton}
            variant="secondary"
            aria-haspopup="dialog"
            aria-expanded={isSettingsOpen}
            onClick={() => setIsSettingsOpen(true)}
          >
            <Settings2 aria-hidden="true" size={17} />
            <span>{t("shell.settings.open")}</span>
          </Button>
          <NoahPulse
            notice={currentNotice ?? undefined}
            loading={
              currentNotice === null &&
              (pulseStatus === "idle" ||
                pulseStatus === "loading" ||
                pulseStatus === "refreshing")
            }
            unavailable={pulseStatus === "error"}
            onOpenAction={openActionPanel}
          />
        </div>
      </header>

      <main className={styles.main}>
        <Outlet context={outletContext} />
      </main>

      <footer className={styles.footer}>
        <span>{t(boundaryCopy.footer)}</span>
        <span>{t(boundaryCopy.connection)}</span>
      </footer>

      <SettingsDrawer
        isOpen={isSettingsOpen}
        onClose={closeSettings}
        returnFocusRef={settingsButtonRef}
      />
      {eventForPanel && actionForPanel ? (
        <AgentActionPanel
          isOpen={isActionPanelOpen}
          event={eventForPanel}
          action={actionForPanel}
          employeeName={linkedEmployee?.name ?? null}
          source={workspace.source}
          onRuntimeChanged={refreshRuntimeProjections}
          onClose={closeActionPanel}
        />
      ) : null}
    </div>
  );
}

function getBoundaryCopy(
  source: "mock" | "http",
  status: ReturnType<typeof useWorkspace>["status"],
): {
  header: TranslationKey;
  footer: TranslationKey;
  connection: TranslationKey;
  state: "ready" | "loading" | "unavailable";
} {
  if (source === "mock") {
    return {
      header: "shell.runtime.mock",
      footer: "shell.footer.mock",
      connection: "shell.footer.offline",
      state: "ready",
    };
  }

  if (status === "error") {
    return {
      header: "shell.runtime.unavailable",
      footer: "shell.footer.http",
      connection: "shell.runtime.unavailable",
      state: "unavailable",
    };
  }

  if (
    status === "idle" ||
    status === "loading" ||
    status === "refreshing"
  ) {
    return {
      header: "shell.runtime.loading",
      footer: "shell.footer.http",
      connection: "shell.runtime.loading",
      state: "loading",
    };
  }

  return {
    header: "shell.runtime.http",
    footer: "shell.footer.http",
    connection: "shell.footer.ready",
    state: "ready",
  };
}
