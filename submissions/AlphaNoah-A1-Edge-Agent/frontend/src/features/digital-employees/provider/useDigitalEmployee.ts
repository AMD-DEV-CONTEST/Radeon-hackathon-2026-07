import { useMemo } from "react";

import { useDigitalEmployees } from "./useDigitalEmployees";

export function useDigitalEmployee(employeeId: string | undefined) {
  const resource = useDigitalEmployees();
  const employee = useMemo(
    () =>
      employeeId
        ? (resource.employees.find(
            (candidate) => candidate.id === employeeId,
          ) ?? null)
        : null,
    [employeeId, resource.employees],
  );

  return {
    ...resource,
    employee,
  };
}
