import * as Dialog from "@radix-ui/react-dialog";
import { FileUp, LockKeyhole, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type {
  Classification,
  DisclosureContext,
  DisclosureTask,
  FileKind,
  RecipientProfile,
  ScenarioPreset,
} from "../../lib/types";
import { titleCase } from "../../lib/utils";
import { Button } from "../../components/ui/Button";
import { IconButton } from "../../components/ui/IconButton";
import { ContextFields } from "./ContextFields";
import { SCENARIO_PRESETS } from "./presets";

interface NewTaskDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (
    file: File,
    context: DisclosureContext,
    requesterId: string,
  ) => Promise<DisclosureTask>;
}

function fileKind(file: File): FileKind | undefined {
  const extension = file.name.split(".").at(-1)?.toLowerCase();
  return extension === "xlsx" || extension === "docx" || extension === "pdf"
    ? extension
    : undefined;
}

export function NewTaskDialog({ open, onOpenChange, onCreate }: NewTaskDialogProps) {
  const [preset, setPreset] = useState<ScenarioPreset>(SCENARIO_PRESETS[0]);
  const [context, setContext] = useState<DisclosureContext>({ ...SCENARIO_PRESETS[0].context });
  const [minimumClassification, setMinimumClassification] = useState<Classification>(
    SCENARIO_PRESETS[0].context.classification,
  );
  const [file, setFile] = useState<File>();
  const [mappingConfirmed, setMappingConfirmed] = useState(false);
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    const initial = SCENARIO_PRESETS[0];
    setPreset(initial);
    setContext({ ...initial.context });
    setMinimumClassification(initial.context.classification);
    setFile(undefined);
    setMappingConfirmed(false);
    setError(undefined);
  }, [open]);

  const acceptedLabel = useMemo(
    () => preset.accepts.map((kind) => `.${kind.toUpperCase()}`).join(", "),
    [preset],
  );

  function applyPreset(next: ScenarioPreset) {
    setPreset(next);
    setContext({ ...next.context });
    setMinimumClassification(next.context.classification);
    setFile(undefined);
    setMappingConfirmed(false);
    setError(undefined);
  }

  function applyRecipient(recipient: RecipientProfile) {
    const next = SCENARIO_PRESETS.find((item) => item.context.recipient === recipient);
    if (next) applyPreset(next);
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setError("Select a synthetic source document.");
      return;
    }
    const kind = fileKind(file);
    if (!kind || !preset.accepts.includes(kind)) {
      setError(`This profile requires ${acceptedLabel}.`);
      return;
    }
    if (!mappingConfirmed) {
      setError("Confirm the controlled purpose mapping before analysis.");
      return;
    }
    setSubmitting(true);
    setError(undefined);
    try {
      await onCreate(file, context, preset.requesterId);
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Task creation failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content" aria-describedby="new-task-description">
          <div className="dialog-header">
            <div>
              <Dialog.Title>New disclosure task</Dialog.Title>
              <Dialog.Description id="new-task-description">
                Synthetic competition data only
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <IconButton label="Close new task dialog">
                <X size={17} aria-hidden="true" />
              </IconButton>
            </Dialog.Close>
          </div>

          <form className="new-task-form" onSubmit={submit}>
            <label className="field field--wide">
              <span>Scenario template</span>
              <select
                aria-label="Scenario template"
                value={preset.id}
                onChange={(event) =>
                  applyPreset(
                    SCENARIO_PRESETS.find((item) => item.id === event.target.value) ??
                      SCENARIO_PRESETS[0],
                  )
                }
              >
                {SCENARIO_PRESETS.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <div className="preset-summary">
              <LockKeyhole size={16} aria-hidden="true" />
              <span>{preset.description}</span>
            </div>

            <ContextFields
              context={context}
              minimumClassification={minimumClassification}
              onChange={setContext}
              onRecipientChange={applyRecipient}
            />

            <label className="file-field">
              <input
                accept={preset.accepts.map((kind) => `.${kind}`).join(",")}
                aria-label="Source document"
                type="file"
                onChange={(event) => {
                  setFile(event.target.files?.[0]);
                  setError(undefined);
                }}
              />
              <FileUp size={22} aria-hidden="true" />
              <span>
                <strong>{file?.name ?? "Choose source document"}</strong>
                <small>{file ? `${titleCase(fileKind(file) ?? "unsupported")} selected` : acceptedLabel}</small>
              </span>
            </label>

            <label className="confirmation-row">
              <input
                checked={mappingConfirmed}
                type="checkbox"
                onChange={(event) => setMappingConfirmed(event.target.checked)}
              />
              <span>
                Confirm controlled purpose mapping: <strong>{titleCase(context.purpose)}</strong>
              </span>
            </label>

            {error ? <p className="form-error" role="alert">{error}</p> : null}

            <div className="dialog-actions">
              <Dialog.Close asChild>
                <Button type="button">Cancel</Button>
              </Dialog.Close>
              <Button disabled={submitting} type="submit" variant="primary">
                {submitting ? "Creating task" : "Create and analyze"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
