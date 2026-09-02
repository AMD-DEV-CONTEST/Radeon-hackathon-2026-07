import { adaptPulseNotice } from "../adapter/pulseNoticeAdapter";
import { mockNoticeInputs } from "../mock/mockAdapterInputs";
import type { PulseNotice } from "../models";
import {
  PulseReadError,
  type PulseDataSource,
  type PulseRequest,
} from "./pulseDataSource";

export class MockPulseDataSource implements PulseDataSource {
  readonly source = "mock" as const;

  constructor(
    private readonly notice: PulseNotice | null =
      buildMockPulseNotice(),
  ) {}

  getInitialPulse(): PulseNotice | null {
    return this.notice;
  }

  async getPulse(
    request: PulseRequest = {},
  ): Promise<PulseNotice | null> {
    if (request.signal?.aborted) {
      throw new PulseReadError(
        "aborted",
        this.source,
        "Pulse read was aborted.",
      );
    }
    return this.notice;
  }
}

function buildMockPulseNotice(): PulseNotice | null {
  const input = mockNoticeInputs[0];
  return input ? adaptPulseNotice(input) : null;
}

export const mockPulseDataSource = new MockPulseDataSource();
