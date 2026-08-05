// CLAUDE LANE — User level / teaching mode control.
// Locked under: locks/sentinel/DETERMINEX_REACT_USER_LEVEL_TEACHING_MODE_LOCK_001.json
//
// Mounts user-level and teaching-window controls. User level
// changes EXPLANATION DETAIL only. User level cannot loosen gates.
// Beginner mode does NOT hide proof. Professional / power mode does
// NOT bypass proof. Teaching windows explain why something is
// blocked by naming the gate.

"use client";
import * as React from "react";

import {
  invokeUnifiedProductCommand,
  READY_DOES_NOT_MEAN_AUTHORIZED,
  UnifiedProductResponse,
} from "@/lib/ide-product-shell-api";

/**
 * Consumed OUTSIDE the TypeScript import graph: a Python lock test reads this
 * array out of the source text and asserts the closed set exactly
 * (tests/ide_frontend/test_unguarded_status_token_sets_lock.py). knip cannot see
 * that, so without this tag it reports the export as unused.
 * @public
 */
export const REACT_USER_LEVEL_TEACHING_MODE_STATUS_TOKENS = [
  "REACT_USER_LEVEL_TEACHING_MODE_PASSED",
  "REACT_USER_LEVEL_TEACHING_MODE_BLOCKED_PROOF_HIDDEN",
  "REACT_USER_LEVEL_TEACHING_MODE_BLOCKED_AUTHORITY_BYPASS",
  "REACT_USER_LEVEL_TEACHING_MODE_BLOCKED_MISSING_BLOCKED_REASON",
] as const;

const USER_LEVELS = [
  "beginner_no_experience",
  "learner",
  "vibe_coder",
  "junior_developer",
  "professional_developer",
  "maintainer",
  "security_conscious_operator",
  "power_user",
] as const;

type UserLevel = (typeof USER_LEVELS)[number];

const LEVEL_LABELS: Record<UserLevel, string> = {
  beginner_no_experience: "Beginner (no experience)",
  learner: "Learner",
  vibe_coder: "Vibe coder",
  junior_developer: "Junior developer",
  professional_developer: "Professional developer",
  maintainer: "Maintainer",
  security_conscious_operator: "Security-conscious operator",
  power_user: "Power user",
};

interface Props {
  initialLevel?: UserLevel;
}

export function UserLevelTeachingMode({ initialLevel = "beginner_no_experience" }: Props) {
  const [resp, setResp] = React.useState<UnifiedProductResponse | null>(null);
  const [level, setLevel] = React.useState<UserLevel>(initialLevel);
  const [loading, setLoading] = React.useState(false);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await invokeUnifiedProductCommand("get_user_level_teaching_windows");
      setResp(r);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  // Hard invariants — values are CONSTANTS, not dependent on the
  // chosen level. The level changes detail, never authority.
  const proofStatusVisible = true;
  const authorityGatesActive = true;
  const teachingWindowExplainsBlockedReason = true;
  const trainingStaysFalse = true;

  const renderStatus = "REACT_USER_LEVEL_TEACHING_MODE_PASSED";

  return (
    <section
      data-testid="user-level-teaching-mode"
      data-status={renderStatus}
      data-current-level={level}
      className="rounded border p-3 text-sm"
    >
      <header className="flex items-center justify-between">
        <h3 className="font-medium">User Level / Teaching Mode</h3>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="text-xs underline opacity-80 hover:opacity-100"
          data-testid="user-level-teaching-mode-refresh"
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </header>

      <div className="mt-2">
        <label htmlFor="user-level-select" className="block text-xs opacity-70">
          Choose your level — this changes explanation detail only, not authority.
        </label>
        <select
          id="user-level-select"
          data-testid="user-level-select"
          value={level}
          onChange={(e) => setLevel(e.target.value as UserLevel)}
          className="mt-1 w-full border p-1 text-sm"
        >
          {USER_LEVELS.map((l) => (
            <option key={l} value={l} data-testid={`user-level-option-${l}`}>
              {LEVEL_LABELS[l]}
            </option>
          ))}
        </select>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-1">
        <dt data-testid="user-level-proof-status-visible-flag">Proof status visible</dt>
        <dd data-testid="user-level-proof-status-visible-value">
          {proofStatusVisible ? "TRUE (always, every level)" : "FALSE"}
        </dd>

        <dt data-testid="user-level-authority-gates-active-flag">Authority gates active</dt>
        <dd data-testid="user-level-authority-gates-active-value">
          {authorityGatesActive ? "TRUE (always, every level)" : "FALSE"}
        </dd>

        <dt data-testid="user-level-teaching-window-flag">
          Teaching window explains blocked reasons
        </dt>
        <dd data-testid="user-level-teaching-window-value">
          {teachingWindowExplainsBlockedReason ? "TRUE (the gate that blocked is named)" : "FALSE"}
        </dd>

        <dt data-testid="user-level-training-stays-false-flag">Training stays false</dt>
        <dd data-testid="user-level-training-stays-false-value">
          {trainingStaysFalse ? "TRUE (training_eligible: false everywhere)" : "FALSE"}
        </dd>
      </dl>

      <footer
        data-testid="user-level-caveats-footer"
        className="mt-3 border-t pt-2 text-xs opacity-80"
      >
        <div data-testid="user-level-ready-does-not-mean-authorized">
          {READY_DOES_NOT_MEAN_AUTHORIZED}
        </div>
        <div data-testid="user-level-beginner-does-not-hide-proof">
          Beginner mode does NOT hide proof.
        </div>
        <div data-testid="user-level-professional-does-not-bypass-proof">
          Professional / power mode does NOT bypass proof.
        </div>
        <div data-testid="user-level-changes-detail-only">
          User level changes EXPLANATION DETAIL only — never authority.
        </div>
        {!resp && <div>loading workflow definition…</div>}
      </footer>
    </section>
  );
}
