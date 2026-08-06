import type {
  DigitalEmployeeProjectionDto,
} from "./digitalEmployeeApiDtos";

const eventIdPattern = /^event_[a-f0-9]{32}$/;
const maximumPublicTextLength = 200;

export class DigitalEmployeeContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DigitalEmployeeContractError";
  }
}

export function decodeDigitalEmployeeProjection(
  value: unknown,
): readonly DigitalEmployeeProjectionDto[] {
  if (!Array.isArray(value)) {
    throw new DigitalEmployeeContractError(
      "digital employees must be an array.",
    );
  }

  const employeeIds = new Set<string>();
  return value.map((item, index) => {
    const employee = record(item, `digital_employees[${index}]`);
    const path = `digital_employees[${index}]`;
    const id = publicString(employee.id, `${path}.id`);
    if (employeeIds.has(id)) {
      throw new DigitalEmployeeContractError(
        `${path}.id must be unique.`,
      );
    }
    employeeIds.add(id);

    const status = oneOf(
      employee.status,
      ["working", "unknown"] as const,
      `${path}.status`,
    );
    const currentEventId = nullableEventId(
      employee.current_event_id,
      `${path}.current_event_id`,
    );
    if (status === "working" && currentEventId === null) {
      throw new DigitalEmployeeContractError(
        `${path}.current_event_id is required while status is working.`,
      );
    }
    if (status === "unknown" && currentEventId !== null) {
      throw new DigitalEmployeeContractError(
        `${path}.current_event_id must be null while status is unknown.`,
      );
    }

    const skillsValue = employee.skills;
    if (!Array.isArray(skillsValue)) {
      throw new DigitalEmployeeContractError(
        `${path}.skills must be an array.`,
      );
    }
    const skillNames = new Set<string>();
    const skills = skillsValue.map((skillValue, skillIndex) => {
      const skillPath = `${path}.skills[${skillIndex}]`;
      const skill = record(skillValue, skillPath);
      const name = publicString(skill.name, `${skillPath}.name`);
      if (skillNames.has(name)) {
        throw new DigitalEmployeeContractError(
          `${skillPath}.name must be unique within an employee.`,
        );
      }
      skillNames.add(name);
      return { name };
    });

    // Constructing a new object is deliberate: additive response fields,
    // including accidental private Runtime data, never enter the View Model.
    return {
      id,
      name: publicString(employee.name, `${path}.name`),
      status,
      current_event_id: currentEventId,
      responsibility: publicString(
        employee.responsibility,
        `${path}.responsibility`,
      ),
      skills,
    };
  });
}

function record(
  value: unknown,
  path: string,
): Record<string, unknown> {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value)
  ) {
    throw new DigitalEmployeeContractError(
      `${path} must be an object.`,
    );
  }
  return value as Record<string, unknown>;
}

function publicString(value: unknown, path: string): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value !== value.trim() ||
    value.length > maximumPublicTextLength
  ) {
    throw new DigitalEmployeeContractError(
      `${path} must be a bounded non-empty string.`,
    );
  }
  return value;
}

function nullableEventId(
  value: unknown,
  path: string,
): string | null {
  if (value === null) {
    return null;
  }
  if (
    typeof value !== "string" ||
    !eventIdPattern.test(value)
  ) {
    throw new DigitalEmployeeContractError(
      `${path} must be a valid Event ID or null.`,
    );
  }
  return value;
}

function oneOf<const T extends readonly string[]>(
  value: unknown,
  expected: T,
  path: string,
): T[number] {
  if (
    typeof value !== "string" ||
    !expected.includes(value as T[number])
  ) {
    throw new DigitalEmployeeContractError(
      `${path} does not match the projection contract.`,
    );
  }
  return value as T[number];
}
