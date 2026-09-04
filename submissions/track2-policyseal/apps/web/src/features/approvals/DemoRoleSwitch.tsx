import { Badge } from "../../components/ui/Badge";
import type { DemoRole } from "../../lib/types";

interface DemoRoleSwitchProps {
  role: DemoRole;
  onRoleChange: (role: DemoRole) => void;
}

export function DemoRoleSwitch({ role, onRoleChange }: DemoRoleSwitchProps) {
  return (
    <section className="role-switch" aria-labelledby="demo-role-title">
      <div className="role-switch__heading">
        <span id="demo-role-title">Demo Role Switch</span>
        <Badge tone="warning">Synthetic</Badge>
      </div>
      <div className="segmented-control" role="group" aria-label="Demo role">
        <button
          aria-pressed={role === "requester"}
          className={role === "requester" ? "is-active" : undefined}
          onClick={() => onRoleChange("requester")}
          type="button"
        >
          Requester
        </button>
        <button
          aria-pressed={role === "policy_reviewer"}
          className={role === "policy_reviewer" ? "is-active" : undefined}
          onClick={() => onRoleChange("policy_reviewer")}
          type="button"
        >
          Reviewer
        </button>
      </div>
    </section>
  );
}
