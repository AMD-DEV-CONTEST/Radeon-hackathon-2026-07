// @vitest-environment node
import { describe, it, expect } from 'vitest'
import dtoSource from './dto.ts?raw'

// Lightweight guard: every domain DTO must declare its backend model via a
// `// maps:` annotation. The authoritative field-by-field check lives in
// scripts/validate_ui_contract.py (run under `make test-governance`).
//
// Only interfaces that carry a `// maps:` annotation are validated here; the
// four overview sub-shapes (TaskStats/RiskStats/DocChangeSummary/RunSummary)
// are structural (backend returns dict/list[dict]) and are intentionally
// unmapped. The authoritative field check is in scripts/validate_ui_contract.py.
const EXPECTED_MAPPED = [
  'LoginRequest',
  'TokenResponse',
  'UserProfile',
  'ProjectCreate',
  'Project',
  'ProjectOverview',
  'UploadResult',
  'ProjectFileEntry',
  'StepTiming',
  'RunState',
  'RunProgress',
  'TaskRecord',
  'TaskCreate',
  'TaskUpdate',
  'TaskStatusTransition',
  'TaskChangeRecord',
  'CandidateTask',
  'ConfirmationRecord',
  'ConfirmationAction',
  'TaskImportDiff',
  'TaskImportResult',
  'OperationAuditRecord',
  'TaskExtractionRequest',
  'TaskExtractionResult',
  'RiskCenterEntry',
  'RiskAssignmentRequest',
  'RiskLifecycleUpdate',
  'ReportDraftEntry',
  'ReportDraftCreate',
  'ReportDraftUpdate',
  'ReportApprovalRequest',
  'ProjectMemberEntry',
  'ProjectMemberAdd',
  'CommentCreate',
  'CommentEntry',
  'NotificationEntry',
  'ErrorDetail',
]

describe('DTO contract annotations', () => {
  for (const name of EXPECTED_MAPPED) {
    it(`declares a // maps: annotation for ${name}`, () => {
      const re = new RegExp(
        `//\\s*maps:\\s*${name}\\s*\\n\\s*export\\s+interface\\s+${name}\\b`,
      )
      expect(re.test(dtoSource)).toBe(true)
    })
  }
})
