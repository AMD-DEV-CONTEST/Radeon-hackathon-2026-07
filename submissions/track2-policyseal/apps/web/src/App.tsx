import { useEffect, useState } from "react";

import { AppShell } from "./components/AppShell";
import { AnalysisProgress } from "./features/tasks/AnalysisProgress";
import { NewTaskDialog } from "./features/tasks/NewTaskDialog";
import { TaskList } from "./features/tasks/TaskList";
import { ReviewWorkspace } from "./features/review/ReviewWorkspace";
import {
  analyzeRevision,
  createTask,
  fetchStageEvents,
  getHealth,
  getTask,
  listTasks,
} from "./lib/api";
import type {
  ApiState,
  DemoRole,
  DisclosureContext,
  DisclosureTask,
  HealthResponse,
  StageEvent,
} from "./lib/types";

export function App() {
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [health, setHealth] = useState<HealthResponse>();
  const [role, setRole] = useState<DemoRole>("requester");
  const [newTaskOpen, setNewTaskOpen] = useState(false);
  const [tasks, setTasks] = useState<DisclosureTask[]>([]);
  const [tasksLoading, setTasksLoading] = useState(true);
  const [selectedTaskId, setSelectedTaskId] = useState<string>();
  const [analysisRevisionId, setAnalysisRevisionId] = useState<string>();
  const [events, setEvents] = useState<Record<string, StageEvent[]>>({});
  const [analysisError, setAnalysisError] = useState<string>();

  useEffect(() => {
    const controller = new AbortController();

    getHealth(controller.signal)
      .then((response) => {
        setHealth(response);
        setApiState("ready");
        return listTasks(controller.signal);
      })
      .then((loadedTasks) => {
        setTasks(loadedTasks);
        setSelectedTaskId((current) => current ?? loadedTasks[0]?.id);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setApiState("offline");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setTasksLoading(false);
      });

    return () => controller.abort();
  }, []);

  async function runAnalysis(task: DisclosureTask): Promise<void> {
    const revision = task.revisions.at(-1);
    if (!revision) return;
    const revisionId = revision.id;
    setAnalysisRevisionId(revisionId);
    setAnalysisError(undefined);
    let sequence = 0;
    let polling = false;

    async function pollEvents() {
      if (polling) return;
      polling = true;
      try {
        const next = await fetchStageEvents(revisionId, sequence);
        if (next.length > 0) {
          sequence = next.at(-1)?.sequence ?? sequence;
          setEvents((current) => ({
            ...current,
            [revisionId]: [...(current[revisionId] ?? []), ...next],
          }));
        }
      } catch {
        // The analysis result still controls the final state; the next poll resumes by sequence.
      } finally {
        polling = false;
      }
    }

    const timer = window.setInterval(() => void pollEvents(), 180);
    try {
      await pollEvents();
      await analyzeRevision(revisionId);
      await pollEvents();
      const refreshed = await getTask(task.id);
      setTasks((current) => current.map((item) => (item.id === refreshed.id ? refreshed : item)));
    } catch (caught) {
      setAnalysisError(caught instanceof Error ? caught.message : "Local analysis failed.");
      try {
        const refreshed = await getTask(task.id);
        setTasks((current) =>
          current.map((item) => (item.id === refreshed.id ? refreshed : item)),
        );
      } catch {
        // Preserve the last local snapshot if refresh is unavailable.
      }
    } finally {
      window.clearInterval(timer);
      setAnalysisRevisionId(undefined);
    }
  }

  async function handleCreate(
    file: File,
    context: DisclosureContext,
    requesterId: string,
  ): Promise<DisclosureTask> {
    const task = await createTask(file, context, requesterId);
    setTasks((current) => [task, ...current]);
    setSelectedTaskId(task.id);
    setNewTaskOpen(false);
    void runAnalysis(task);
    return task;
  }

  async function refreshTask(taskId: string): Promise<void> {
    const refreshed = await getTask(taskId);
    setTasks((current) =>
      current.map((item) => (item.id === refreshed.id ? refreshed : item)),
    );
    setSelectedTaskId(refreshed.id);
  }

  const selectedTask = tasks.find((task) => task.id === selectedTaskId);
  const selectedRevision = selectedTask?.revisions.at(-1);

  return (
    <AppShell
      apiState={apiState}
      apiVersion={health?.version}
      role={role}
      onRoleChange={setRole}
      onNewTask={() => setNewTaskOpen(true)}
    >
      <div className="task-workspace">
        <TaskList
          loading={tasksLoading}
          selectedTaskId={selectedTaskId}
          tasks={tasks}
          onSelect={setSelectedTaskId}
        />

        {selectedTask && selectedRevision && (
          selectedRevision.id === analysisRevisionId || selectedRevision.status === "draft"
        ) ? (
          <AnalysisProgress
            error={selectedRevision.id === analysisRevisionId ? analysisError : undefined}
            events={events[selectedRevision.id] ?? []}
            revision={selectedRevision}
            running={selectedRevision.id === analysisRevisionId}
          />
        ) : selectedTask && selectedRevision ? (
          <ReviewWorkspace
            apiState={apiState}
            revision={selectedRevision}
            role={role}
            task={selectedTask}
            onFormalRevision={async () => refreshTask(selectedTask.id)}
            onRevisionChanged={async () => refreshTask(selectedTask.id)}
          />
        ) : (
          <section className="empty-state" aria-labelledby="empty-state-title">
            <div className="empty-state__mark" aria-hidden="true">PS</div>
            <h2 id="empty-state-title">No disclosure task selected</h2>
            <p>Start with a synthetic XLSX, DOCX, or text PDF.</p>
          </section>
        )}
      </div>

      <NewTaskDialog
        open={newTaskOpen}
        onCreate={handleCreate}
        onOpenChange={setNewTaskOpen}
      />
    </AppShell>
  );
}
