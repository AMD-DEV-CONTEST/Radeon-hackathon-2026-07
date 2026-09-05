import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { DeliveryPreview } from './DeliveryPreview';
import { COMPLETE_DELIVERY_PREVIEW } from './fixtures';

describe('E7 private preview and destructive confirmation', () => {
  it('shows a private preview while external export remains approval-blocked', () => {
    render(<DeliveryPreview preview={COMPLETE_DELIVERY_PREVIEW} />);
    expect(screen.getByTestId('delivery-private-preview')).toBeVisible();
    expect(screen.getByText(/does not grant external-share approval/i)).toBeVisible();
    expect(screen.getByRole('button', {name: /Export HTML/})).toBeDisabled();
    expect(screen.getByText('en')).toBeVisible();
    expect(screen.queryByText('选择证据')).not.toBeInTheDocument();
  });

  it('enables external export only for a valid exact-bound approval', async () => {
    const onExport = vi.fn();
    const user = userEvent.setup();
    render(
      <DeliveryPreview
        preview={{...COMPLETE_DELIVERY_PREVIEW, approval_status: 'VALID'}}
        onExternalExport={onExport}
      />,
    );
    await user.click(screen.getByRole('button', {name: /Export HTML/}));
    expect(onExport).toHaveBeenCalledOnce();
  });

  it('requires a distinct request and acknowledged second confirmation', async () => {
    const onRequest = vi.fn();
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(
      <DeliveryPreview
        preview={COMPLETE_DELIVERY_PREVIEW}
        onRequestDeletion={onRequest}
        onConfirmDeletion={onConfirm}
      />,
    );
    await user.click(screen.getByRole('button', {name: 'Request deletion'}));
    expect(onRequest).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole('button', {name: 'Confirm deletion'})).toBeDisabled();
    await user.click(
      screen.getByRole('checkbox', {name: /explicitly confirm this destructive action/i}),
    );
    await user.click(screen.getByRole('button', {name: 'Confirm deletion'}));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it('marks a historical preview as superseded and blocks export', () => {
    render(
      <DeliveryPreview
        preview={{
          ...COMPLETE_DELIVERY_PREVIEW,
          state: 'SUPERSEDED',
          approval_status: 'VALID',
        }}
      />,
    );
    expect(screen.getByTestId('delivery-superseded')).toHaveTextContent('SUPERSEDED');
    expect(screen.getByRole('button', {name: /Export HTML/})).toBeDisabled();
  });

  it('shows distinct route-draft, relation, and renderer identities', () => {
    render(<DeliveryPreview preview={COMPLETE_DELIVERY_PREVIEW} />);
    expect(screen.getByText(COMPLETE_DELIVERY_PREVIEW.route_draft_hash)).toBeVisible();
    expect(screen.getByText(COMPLETE_DELIVERY_PREVIEW.renderer_input_identity)).toBeVisible();
    expect(screen.getByText(COMPLETE_DELIVERY_PREVIEW.relation_projection_hash)).toBeVisible();
  });
});
