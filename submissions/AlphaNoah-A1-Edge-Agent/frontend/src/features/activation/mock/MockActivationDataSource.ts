import {
  ActivationError,
  type ActivationCommand,
  type ActivationDataSource,
  type ActivationSnapshot,
} from "../models";

export class MockActivationDataSource
  implements ActivationDataSource
{
  readonly source = "mock" as const;
  activateCalls = 0;
  getEventCalls = 0;

  constructor(
    private readonly result: ActivationSnapshot | Error,
  ) {}

  async activate(
    command: ActivationCommand,
  ): Promise<ActivationSnapshot> {
    this.activateCalls += 1;
    abortIfNeeded(command.signal);
    return this.readResult();
  }

  async getEvent(
    _eventId: string,
    options?: { readonly signal?: AbortSignal },
  ): Promise<ActivationSnapshot> {
    this.getEventCalls += 1;
    abortIfNeeded(options?.signal);
    return this.readResult();
  }

  private readResult(): ActivationSnapshot {
    if (this.result instanceof Error) {
      throw this.result;
    }
    return this.result;
  }
}

function abortIfNeeded(signal: AbortSignal | undefined): void {
  if (signal?.aborted) {
    throw new ActivationError({
      code: "aborted",
      source: "mock",
      message: "Mock activation was aborted.",
      retryable: false,
    });
  }
}
