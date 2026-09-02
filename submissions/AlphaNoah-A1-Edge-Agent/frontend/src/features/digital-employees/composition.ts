/**
 * Concrete data sources are selected only at the application composition root.
 * Pages and presentation components consume provider hooks from the public index.
 */
export {
  MockDigitalEmployeeDataSource,
  mockDigitalEmployeeDataSource,
} from "./mock/MockDigitalEmployeeDataSource";
export {
  HttpDigitalEmployeeDataSource,
} from "./api/HttpDigitalEmployeeDataSource";

import {
  HttpDigitalEmployeeDataSource,
} from "./api/HttpDigitalEmployeeDataSource";

export const httpDigitalEmployeeDataSource =
  new HttpDigitalEmployeeDataSource();
