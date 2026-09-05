import { useState } from 'react';
import { Badge, Mono, Panel } from '../../components/primitives';
import type { DeliveryPreviewV1 } from './types';
import './delivery.css';

type Props = {
  preview: DeliveryPreviewV1;
  onPrivateDownload?: () => void;
  onExternalExport?: () => void;
  onRequestDeletion?: () => void;
  onConfirmDeletion?: () => void;
};

export function DeliveryPreview({
  preview,
  onPrivateDownload,
  onExternalExport,
  onRequestDeletion,
  onConfirmDeletion,
}: Props) {
  const [deletionArmed, setDeletionArmed] = useState(false);
  const [deletionAcknowledged, setDeletionAcknowledged] = useState(false);
  const externalAllowed = preview.approval_status === 'VALID' && preview.state === 'CURRENT';

  const requestDeletion = () => {
    setDeletionArmed(true);
    setDeletionAcknowledged(false);
    onRequestDeletion?.();
  };

  const confirmDeletion = () => {
    if (!deletionArmed || !deletionAcknowledged) return;
    onConfirmDeletion?.();
  };

  return (
    <section className="delivery" data-testid="delivery-preview">
      {preview.state === 'SUPERSEDED' ? (
        <div className="notice notice--warn" role="status" data-testid="delivery-superseded">
          SUPERSEDED — this historical output is not the current deliverable.
        </div>
      ) : null}
      <Panel
        title="Private in-app preview"
        testId="delivery-private-preview"
        actions={<Badge tone="info">{preview.language}</Badge>}
      >
        <p className="delivery__private-label">
          Private preview only. This view does not grant external-share approval.
        </p>
        <h3>{preview.title}</h3>
        <p>{preview.summary}</p>
        <div className="delivery__sections">
          {preview.sections.map(section => (
            <details open key={section.heading}>
              <summary>{section.heading}</summary>
              {section.claims.map(claim => (
                <p key={`${section.heading}-${claim.statement_ids.join('-')}`}>
                  {claim.text}
                </p>
              ))}
            </details>
          ))}
        </div>
      </Panel>

      <Panel title="Exact delivery identity" testId="delivery-identity">
        <dl className="delivery__identity">
          <div><dt>Route draft</dt><dd><Mono>{preview.route_draft_id}</Mono></dd></div>
          <div><dt>Asset</dt><dd><Mono>{preview.asset_id}</Mono></dd></div>
          <div><dt>Version</dt><dd><Mono>{preview.version_id}</Mono></dd></div>
          <div><dt>Asset hash</dt><dd><Mono>{preview.asset_version_hash}</Mono></dd></div>
          <div><dt>Relation projection</dt><dd><Mono>{preview.relation_projection_hash}</Mono></dd></div>
          <div><dt>Route draft hash</dt><dd><Mono>{preview.route_draft_hash}</Mono></dd></div>
          <div><dt>Renderer input</dt><dd><Mono>{preview.renderer_input_identity}</Mono></dd></div>
          <div><dt>Privacy state</dt><dd><Mono>{preview.privacy_state_hash}</Mono></dd></div>
        </dl>
      </Panel>

      <Panel title="Export and deletion" testId="delivery-actions">
        <p>
          External export approval: <Badge tone={externalAllowed ? 'ok' : 'warn'}>
            {preview.approval_status}
          </Badge>
        </p>
        <div className="row">
          <button className="btn" onClick={onPrivateDownload}>
            Download private HTML + Markdown + JSON
          </button>
          <button
            className="btn btn--primary"
            disabled={!externalAllowed}
            onClick={onExternalExport}
          >
            Export HTML + Markdown + JSON
          </button>
          <button className="btn btn--danger" onClick={requestDeletion}>
            Request deletion
          </button>
        </div>
        {deletionArmed ? (
          <div className="delivery__deletion" role="alert">
            <p>
              This removes product-managed content and exports. External or user-created copies
              cannot be recalled.
            </p>
            <label>
              <input
                type="checkbox"
                checked={deletionAcknowledged}
                onChange={event => setDeletionAcknowledged(event.target.checked)}
              />
              I understand and explicitly confirm this destructive action.
            </label>
            <button
              className="btn btn--danger"
              disabled={!deletionAcknowledged}
              onClick={confirmDeletion}
            >
              Confirm deletion
            </button>
          </div>
        ) : null}
      </Panel>
    </section>
  );
}
