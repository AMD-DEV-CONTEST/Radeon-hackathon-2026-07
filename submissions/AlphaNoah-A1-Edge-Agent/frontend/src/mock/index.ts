import type { PulseNotice } from "../features/runtime";
import { mockWorkspaceDataSource } from "../features/runtime/composition";

const notice =
  mockWorkspaceDataSource.getInitialSnapshot().activeNotices[0];

if (!notice) {
  throw new Error("The Pulse compatibility fixture is missing.");
}

/**
 * Test compatibility export. Production UI reads this notice through
 * WorkspaceProvider/usePulse instead of importing this fixture.
 */
export const mockPulseNotice: PulseNotice & {
  readonly activityId: string;
} = {
  ...notice,
  activityId: notice.eventId,
};
