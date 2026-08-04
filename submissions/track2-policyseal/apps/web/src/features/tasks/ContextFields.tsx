import type { Dispatch, SetStateAction } from "react";

import type { Classification, DisclosureContext, RecipientProfile } from "../../lib/types";
import { titleCase } from "../../lib/utils";
import { CHANNEL_OPTIONS, PURPOSE_OPTIONS, SCENARIO_PRESETS } from "./presets";

const CLASSIFICATION_RANK: Record<Classification, number> = {
  public: 0,
  internal: 1,
  confidential: 2,
  strictly_confidential: 3,
};

interface ContextFieldsProps {
  context: DisclosureContext;
  minimumClassification: Classification;
  onChange: Dispatch<SetStateAction<DisclosureContext>>;
  onRecipientChange: (recipient: RecipientProfile) => void;
}

export function ContextFields({
  context,
  minimumClassification,
  onChange,
  onRecipientChange,
}: ContextFieldsProps) {
  const recipients = Array.from(
    new Set(SCENARIO_PRESETS.map((preset) => preset.context.recipient)),
  );
  const classificationOptions = (
    ["public", "internal", "confidential", "strictly_confidential"] as Classification[]
  ).filter((item) => CLASSIFICATION_RANK[item] >= CLASSIFICATION_RANK[minimumClassification]);

  return (
    <div className="context-fields">
      <label className="field">
        <span>Recipient profile</span>
        <select
          aria-label="Recipient profile"
          value={context.recipient}
          onChange={(event) => onRecipientChange(event.target.value as RecipientProfile)}
        >
          {recipients.map((recipient) => (
            <option key={recipient} value={recipient}>
              {titleCase(recipient)}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Recipient organization</span>
        <input aria-label="Recipient organization" readOnly value={context.organization} />
      </label>

      <label className="field field--wide">
        <span>Recipient identity</span>
        <input aria-label="Recipient identity" readOnly value={context.recipient_id} />
      </label>

      <label className="field">
        <span>Controlled purpose</span>
        <select
          aria-label="Controlled purpose"
          value={context.purpose}
          onChange={(event) =>
            onChange((current) => ({
              ...current,
              purpose: event.target.value as DisclosureContext["purpose"],
            }))
          }
        >
          {PURPOSE_OPTIONS.map((purpose) => (
            <option key={purpose} value={purpose}>
              {titleCase(purpose)}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Disclosure channel</span>
        <select
          aria-label="Disclosure channel"
          value={context.channel}
          onChange={(event) =>
            onChange((current) => ({
              ...current,
              channel: event.target.value as DisclosureContext["channel"],
            }))
          }
        >
          {CHANNEL_OPTIONS.map((channel) => (
            <option key={channel} value={channel}>
              {titleCase(channel)}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Classification</span>
        <select
          aria-label="Classification"
          value={context.classification}
          onChange={(event) =>
            onChange((current) => ({
              ...current,
              classification: event.target.value as Classification,
            }))
          }
        >
          {classificationOptions.map((classification) => (
            <option key={classification} value={classification}>
              {titleCase(classification)}
            </option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Policy version</span>
        <select aria-label="Policy version" disabled value={context.policy_version}>
          <option value="1.0.0">Policy 1.0.0</option>
        </select>
      </label>
    </div>
  );
}
