/**
 * Wire contract for GET /api/digital-employees.
 *
 * These names intentionally remain snake_case and are kept out of the
 * feature's public View Model barrel.
 */
export interface DigitalEmployeeProjectionDto {
  readonly id: string;
  readonly name: string;
  readonly status: "working" | "unknown";
  readonly current_event_id: string | null;
  readonly responsibility: string;
  readonly skills: readonly {
    readonly name: string;
  }[];
}
