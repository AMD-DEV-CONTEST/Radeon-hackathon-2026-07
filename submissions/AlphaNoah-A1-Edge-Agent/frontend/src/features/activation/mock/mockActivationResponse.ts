import type { DemoActivationResponseDto } from "../api/activationApiDtos";

export const mockActivationResponse: DemoActivationResponseDto = {
  projection_version: "f03c-demo-v1",
  replayed: false,
  event: {
    event_id: "event_0123456789abcdef0123456789abcdef",
    event_type: "device_not_shutdown",
    source: "demo_activation",
    timestamp: "2026-07-30T10:35:00+08:00",
    status: "PENDING_HUMAN_REVIEW",
    severity: "HIGH",
    asset_id: "A08-AIRCON",
    location: "Restaurant-Private-Room-A08",
    description: "A08 air conditioner remained on.",
  },
  responsibility: {
    owner_id: "maintenance_001",
    owner_name: "Equipment Maintenance",
    match_type: "asset",
    matched_key: "A08-AIRCON",
  },
  analysis: {
    detected_issue: "Device remained active outside schedule.",
    reasoning_summary:
      "Shutdown state conflicts with the operating schedule.",
    confidence: 0.94,
    requires_human_review: true,
    knowledge_sources: ["ops://aircon/shutdown"],
  },
  notification: {
    notification_id: "notification_1",
    status: "CREATED",
    created_at: "2026-07-30T10:35:03+08:00",
  },
  human_review: {
    decision_id: "decision_1",
    status: "PENDING_HUMAN_REVIEW",
    required: true,
    allowed_actions: ["approve", "reject"],
  },
  work_records: [
    {
      id: "audit_1",
      sequence: 1,
      occurred_at: "2026-07-30T10:32:00+08:00",
      kind: "event_received",
      title: "Site event received",
      event_id: "event_0123456789abcdef0123456789abcdef",
      task_id: null,
    },
    {
      id: "audit_2",
      sequence: 2,
      occurred_at: "2026-07-30T10:35:00+08:00",
      kind: "human_review",
      title: "Human review requested",
      event_id: "event_0123456789abcdef0123456789abcdef",
      task_id: null,
    },
  ],
  quality: {
    availability: "available",
    unknown_fields: [],
    contract_warnings: [],
  },
};
