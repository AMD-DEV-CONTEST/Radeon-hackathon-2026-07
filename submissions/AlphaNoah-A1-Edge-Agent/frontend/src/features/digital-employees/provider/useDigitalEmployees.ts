import { useMemo } from "react";

import type { DigitalEmployeeView } from "../types";
import { useDigitalEmployeeContext } from "./DigitalEmployeeProvider";

export function useDigitalEmployees() {
  const resource = useDigitalEmployeeContext();
  const collection = resource.data;
  const employees = useMemo<readonly DigitalEmployeeView[]>(
    () => collection?.employees ?? [],
    [collection],
  );

  return {
    ...resource,
    data: collection,
    collection,
    employees,
  };
}
