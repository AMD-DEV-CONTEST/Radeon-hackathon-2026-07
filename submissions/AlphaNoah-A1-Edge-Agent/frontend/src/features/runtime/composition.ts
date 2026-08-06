/**
 * Application-composition exports.
 *
 * UI code should consume the public View Models and hooks from `./index`.
 * Only the application root or tests should choose a concrete data source.
 */
export { HttpWorkspaceDataSource } from "./api/HttpWorkspaceDataSource";
export { HttpPulseDataSource } from "./pulse/HttpPulseDataSource";
export { HttpProviderRuntimeDataSource } from "./status/api/HttpProviderRuntimeDataSource";
export {
  MockWorkspaceDataSource,
  mockWorkspaceDataSource,
} from "./mock/MockWorkspaceDataSource";
export {
  MockPulseDataSource,
  mockPulseDataSource,
} from "./pulse/MockPulseDataSource";
export {
  MockProviderRuntimeDataSource,
  mockProviderRuntimeDataSource,
  mockProviderRuntimeSnapshot,
} from "./status/mock/MockProviderRuntimeDataSource";

import { HttpWorkspaceDataSource } from "./api/HttpWorkspaceDataSource";
import { HttpPulseDataSource } from "./pulse/HttpPulseDataSource";
import { HttpProviderRuntimeDataSource } from "./status/api/HttpProviderRuntimeDataSource";

export const httpWorkspaceDataSource =
  new HttpWorkspaceDataSource();
export const httpPulseDataSource = new HttpPulseDataSource();
export const httpProviderRuntimeDataSource =
  new HttpProviderRuntimeDataSource();
