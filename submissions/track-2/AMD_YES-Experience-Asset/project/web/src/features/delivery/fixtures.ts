import type { DeliveryPreviewV1 } from './types';

const DRAFT_HASH = '93d3c1777f5a9e475dd77c2f3a53f59d5986b99d50a8e8ea2a2ae4f265fdf145';
const RENDERER_HASH = '83aa99dce8e5f7325cbbeb5848c5b15dde28f3739ae742d9c31aee921e3626d8';

export const COMPLETE_DELIVERY_PREVIEW: DeliveryPreviewV1 = {
  route_draft_id: '50000000-0000-4000-8000-000000000001',
  asset_id: '10000000-0000-4000-8000-000000000001',
  version_id: '10000000-0000-4000-8000-000000000101',
  asset_version_hash: '1'.repeat(64),
  lineage_parent_version_id: null,
  relation_projection_hash: '3'.repeat(64),
  route: 'PUBLIC',
  language: 'en',
  route_draft_hash: DRAFT_HASH,
  renderer_input_identity: RENDERER_HASH,
  privacy_state_hash: '2'.repeat(64),
  state: 'CURRENT',
  approval_status: 'MISSING',
  title: 'What two chair trials clarified',
  summary: 'Two anonymized trials produced one bounded personal selection lesson.',
  sections: [
    {
      heading: 'Decision evidence',
      claims: [{
        text: 'The second chair fit the stated trial preferences better.',
        statement_ids: ['10000000-0000-4000-8000-000000000012'],
      }],
    },
    {
      heading: 'Transfer boundary',
      claims: [{
        text: 'This personal fit result is not a universal recommendation.',
        statement_ids: ['10000000-0000-4000-8000-000000000013'],
      }],
    },
  ],
};
