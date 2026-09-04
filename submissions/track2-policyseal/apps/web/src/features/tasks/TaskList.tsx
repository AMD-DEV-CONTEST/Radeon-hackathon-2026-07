import { FileSpreadsheet, FileText, ScrollText } from "lucide-react";

import { Badge } from "../../components/ui/Badge";
import type { DisclosureTask } from "../../lib/types";
import { formatDate, shortId, statusTone, titleCase } from "../../lib/utils";

interface TaskListProps {
  tasks: DisclosureTask[];
  selectedTaskId?: string;
  loading: boolean;
  onSelect: (taskId: string) => void;
}

function FileIcon({ kind }: { kind: DisclosureTask["file_kind"] }) {
  if (kind === "xlsx") return <FileSpreadsheet size={17} aria-hidden="true" />;
  if (kind === "pdf") return <ScrollText size={17} aria-hidden="true" />;
  return <FileText size={17} aria-hidden="true" />;
}

export function TaskList({ tasks, selectedTaskId, loading, onSelect }: TaskListProps) {
  return (
    <section className="task-list" aria-labelledby="task-list-title">
      <div className="panel-heading">
        <div>
          <h2 id="task-list-title">Tasks</h2>
          <p>{loading ? "Loading local records" : `${tasks.length} local record${tasks.length === 1 ? "" : "s"}`}</p>
        </div>
      </div>

      <div className="task-list__items">
        {tasks.map((task) => {
          const revision = task.revisions.at(-1);
          return (
            <button
              className={`task-row${selectedTaskId === task.id ? " task-row--selected" : ""}`}
              key={task.id}
              onClick={() => onSelect(task.id)}
              type="button"
            >
              <span className="task-row__icon">
                <FileIcon kind={task.file_kind} />
              </span>
              <span className="task-row__main">
                <strong>{titleCase(revision?.context.recipient ?? task.file_kind)}</strong>
                <small>{titleCase(revision?.context.purpose ?? task.file_kind)}</small>
                <span>{shortId(task.id)} / {formatDate(task.created_at)}</span>
              </span>
              {revision ? (
                <Badge tone={statusTone(revision.status)}>{titleCase(revision.status)}</Badge>
              ) : null}
            </button>
          );
        })}

        {!loading && tasks.length === 0 ? (
          <div className="task-list__empty">No task records yet.</div>
        ) : null}
      </div>
    </section>
  );
}
