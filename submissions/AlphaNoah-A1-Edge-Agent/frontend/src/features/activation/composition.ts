export { HttpActivationDataSource } from "./api/HttpActivationDataSource";
export { MockActivationDataSource } from "./mock/MockActivationDataSource";

import { HttpActivationDataSource } from "./api/HttpActivationDataSource";

export const httpActivationDataSource =
  new HttpActivationDataSource();
