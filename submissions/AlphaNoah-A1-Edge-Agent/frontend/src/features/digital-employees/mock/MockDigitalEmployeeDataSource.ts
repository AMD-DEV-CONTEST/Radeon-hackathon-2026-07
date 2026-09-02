import {
  DigitalEmployeeReadError,
  type DigitalEmployeeCollection,
  type DigitalEmployeeDataSource,
} from "../types";
import { mockDigitalEmployeeCollection } from "./mockDigitalEmployees";

export class MockDigitalEmployeeDataSource
  implements DigitalEmployeeDataSource
{
  readonly source = "mock" as const;

  constructor(
    private readonly collection: DigitalEmployeeCollection =
      mockDigitalEmployeeCollection,
  ) {}

  getInitialCollection(): DigitalEmployeeCollection {
    return this.collection;
  }

  async getEmployees(options?: {
    readonly signal?: AbortSignal;
  }): Promise<DigitalEmployeeCollection> {
    if (options?.signal?.aborted) {
      throw new DigitalEmployeeReadError(
        "aborted",
        this.source,
        "Digital employee read was aborted.",
      );
    }

    return this.collection;
  }
}

export const mockDigitalEmployeeDataSource =
  new MockDigitalEmployeeDataSource();
