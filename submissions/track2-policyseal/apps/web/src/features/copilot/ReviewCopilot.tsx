import * as AlertDialog from "@radix-ui/react-alert-dialog";
import {
  Bot,
  CornerDownRight,
  GitBranch,
  LoaderCircle,
  MapPin,
  Send,
  ShieldQuestion,
  X,
} from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { IconButton } from "../../components/ui/IconButton";
import {
  sendCopilotMessage,
  startCopilotThread,
  submitExceptionDraft,
} from "../../lib/api";
import type {
  ApiState,
  Approval,
  CopilotReply,
  DemoRole,
  DisclosureTask,
  Revision,
} from "../../lib/types";
import { shortId, titleCase } from "../../lib/utils";

interface Exchange {
  prompt: string;
  reply: CopilotReply;
}

interface ReviewCopilotProps {
  task: DisclosureTask;
  revision: Revision;
  role: DemoRole;
  apiState: ApiState;
  selectedLocation?: string;
  onSelectLocation: (location: string) => void;
  onApprovalCreated: (approval: Approval) => void;
}

const SUGGESTIONS = [
  "Explain the selected decision.",
  "What if the purpose is annual financial audit?",
  "Draft an exception for the custom SLA.",
];

export function ReviewCopilot({
  task,
  revision,
  role,
  apiState,
  selectedLocation,
  onSelectLocation,
  onApprovalCreated,
}: ReviewCopilotProps) {
  const [threadId, setThreadId] = useState<string>();
  const [input, setInput] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [confirmDraftId, setConfirmDraftId] = useState<string>();
  const [submittingDraft, setSubmittingDraft] = useState(false);
  const [submittedDrafts, setSubmittedDrafts] = useState<Set<string>>(new Set());

  useEffect(() => {
    setThreadId(undefined);
    setInput("");
    setExchanges([]);
    setError(undefined);
    setConfirmDraftId(undefined);
    setSubmittedDrafts(new Set());
  }, [revision.id, task.id]);

  async function ask(message: string) {
    const trimmed = message.trim();
    if (!trimmed || busy || apiState !== "ready") return;
    setBusy(true);
    setError(undefined);
    try {
      let activeThread = threadId;
      if (!activeThread) {
        const thread = await startCopilotThread(
          task.id,
          revision.id,
          `Revision ${revision.revision_number}`,
        );
        activeThread = thread.thread_id;
        setThreadId(activeThread);
      }
      const reply = await sendCopilotMessage(activeThread, task.id, trimmed);
      setExchanges((current) => [...current, { prompt: trimmed, reply }]);
      setInput("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Review Copilot is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(input);
  }

  async function confirmException() {
    if (!confirmDraftId) return;
    setSubmittingDraft(true);
    setError(undefined);
    try {
      const result = await submitExceptionDraft(confirmDraftId, task.requester_id);
      setSubmittedDrafts((current) => new Set(current).add(confirmDraftId));
      onApprovalCreated(result.approval);
      setConfirmDraftId(undefined);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The exception request was not submitted.",
      );
      setConfirmDraftId(undefined);
    } finally {
      setSubmittingDraft(false);
    }
  }

  const unavailable = apiState !== "ready";

  return (
    <section className="copilot-panel" aria-labelledby="copilot-title">
      <header className="copilot-heading">
        <span className="operation-panel__icon" aria-hidden="true"><Bot size={17} /></span>
        <div>
          <h3 id="copilot-title">Review Copilot</h3>
          <p>Task-local explanations, what-if simulations, and exception drafts</p>
        </div>
        <Badge tone={unavailable ? "danger" : "info"}>{unavailable ? "Unavailable" : "Local"}</Badge>
      </header>

      <div className="copilot-suggestions" aria-label="Suggested review commands">
        {SUGGESTIONS.map((suggestion) => (
          <button disabled={busy || unavailable} key={suggestion} onClick={() => void ask(suggestion)} type="button">
            <CornerDownRight size={13} aria-hidden="true" />{suggestion}
          </button>
        ))}
      </div>

      <div className="copilot-transcript" aria-live="polite">
        {exchanges.length === 0 ? (
          <p className="copilot-empty">
            <ShieldQuestion size={18} aria-hidden="true" /> Ask about a decision after inspecting its policy evidence.
          </p>
        ) : exchanges.map(({ prompt, reply }) => (
          <article className="copilot-exchange" key={`${reply.thread_id}-${reply.turn_number}`}>
            <p className="copilot-prompt"><strong>Turn {reply.turn_number}</strong>{prompt}</p>
            <div className="copilot-reply">
              <div className="copilot-reply__meta">
                <Badge tone="neutral">{titleCase(reply.intent)}</Badge>
                {reply.simulation_id ? <Badge tone="warning"><GitBranch size={11} />Simulation / non-downloadable</Badge> : null}
              </div>
              <p>{reply.text}</p>
              <div className="copilot-citations" aria-label={`Citations for turn ${reply.turn_number}`}>
                {reply.citations.map((citation) => (
                  <button
                    className={citation.location === selectedLocation ? "is-selected" : undefined}
                    key={`${reply.turn_number}-${citation.location}`}
                    onClick={() => onSelectLocation(citation.location)}
                    type="button"
                  >
                    <MapPin size={12} aria-hidden="true" />
                    <span>{citation.location}</span>
                    <small>{citation.rule_ids.join(", ")}</small>
                  </button>
                ))}
              </div>
              {reply.exception_draft_id ? (
                <div className="exception-draft">
                  <div>
                    <strong>Exception draft {shortId(reply.exception_draft_id)}</strong>
                    <small>{submittedDrafts.has(reply.exception_draft_id) ? "Submitted for independent review" : "Draft only / no policy override"}</small>
                  </div>
                  <Button
                    disabled={
                      submittedDrafts.has(reply.exception_draft_id) ||
                      revision.status !== "awaiting_approval" ||
                      role !== "requester"
                    }
                    onClick={() => setConfirmDraftId(reply.exception_draft_id ?? undefined)}
                    size="small"
                    variant="primary"
                  >
                    {submittedDrafts.has(reply.exception_draft_id) ? "Submitted" : "Submit request"}
                  </Button>
                </div>
              ) : null}
            </div>
          </article>
        ))}
      </div>

      {error ? <p className="operation-error copilot-error" role="alert">{error}</p> : null}
      <form className="copilot-composer" onSubmit={submit}>
        <label htmlFor="copilot-message">Ask about this revision</label>
        <div>
          <textarea
            disabled={busy || unavailable}
            id="copilot-message"
            maxLength={1000}
            onChange={(event) => setInput(event.target.value)}
            placeholder={unavailable ? "Local review service unavailable" : "Explain a rule, simulate a context, or draft an exception"}
            rows={2}
            value={input}
          />
          <IconButton
            className="icon-button--primary"
            disabled={busy || unavailable || !input.trim()}
            label="Send review message"
            type="submit"
          >
            {busy ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />}
          </IconButton>
        </div>
      </form>

      <AlertDialog.Root open={Boolean(confirmDraftId)} onOpenChange={(open) => !open && setConfirmDraftId(undefined)}>
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="dialog-overlay" />
          <AlertDialog.Content className="alert-dialog-content">
            <div className="alert-dialog-icon"><ShieldQuestion size={20} aria-hidden="true" /></div>
            <AlertDialog.Title>Submit exception request?</AlertDialog.Title>
            <AlertDialog.Description>
              This creates approval work for the exact immutable revision. It does not change a decision or bypass policy.
            </AlertDialog.Description>
            <div className="dialog-actions">
              <AlertDialog.Cancel asChild><Button disabled={submittingDraft}>Cancel</Button></AlertDialog.Cancel>
              <AlertDialog.Action asChild>
                <Button disabled={submittingDraft} onClick={() => void confirmException()} variant="primary">
                  {submittingDraft ? "Submitting" : "Confirm submission"}
                </Button>
              </AlertDialog.Action>
            </div>
            <AlertDialog.Cancel className="alert-dialog-close" aria-label="Close confirmation"><X size={16} /></AlertDialog.Cancel>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </section>
  );
}
