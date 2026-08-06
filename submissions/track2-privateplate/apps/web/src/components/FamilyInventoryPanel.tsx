import type { HouseholdContext } from "../api";
import { InventoryImageIntake } from "./InventoryImageIntake";
import {
  foodName,
  formatGrams,
  HEALTH_TAG_NAMES,
  ROLE_NAMES
} from "../formatters";

type FamilyInventoryPanelProps = {
  context: HouseholdContext | null;
  selectedDinerIds: string[];
  busy: boolean;
  confirmationPending: boolean;
  operable: boolean;
  onToggleDiner: (memberId: string) => void;
  onSendToAgent: (text: string) => void;
};

export function FamilyInventoryPanel({
  context,
  selectedDinerIds,
  busy,
  confirmationPending,
  operable,
  onToggleDiner,
  onSendToAgent
}: FamilyInventoryPanelProps) {
  return (
    <aside className="panel panel-family">
      <div className="panel-header">
        <h2>家庭</h2>
        <span>已选 {selectedDinerIds.length} 人</span>
      </div>
      <div className="panel-body">
        <p className="muted compact-line">点选本餐用餐成员</p>
        {!context ? (
          <p className="empty-state" role="status">
            读取中…
          </p>
        ) : (
          context.members.map((member) => (
            <div
              className={`member-card member-selectable ${
                selectedDinerIds.includes(member.id) ? "selected" : ""
              }`}
              key={member.id}
            >
              <label className="member-toggle">
                <input
                  type="checkbox"
                  checked={selectedDinerIds.includes(member.id)}
                  disabled={busy || confirmationPending}
                  onChange={() => onToggleDiner(member.id)}
                  aria-describedby={`member-details-${member.id}`}
                />
                <span>
                  <strong>{member.displayName}</strong>{" "}
                  <span className="muted">
                    {ROLE_NAMES[member.roleLabel] ?? member.roleLabel}
                  </span>
                </span>
              </label>
              <div id={`member-details-${member.id}`} className="tag-row">
                {context.constraints
                  .filter((constraint) => constraint.memberId === member.id)
                  .slice(0, 2)
                  .map((constraint) => (
                    <span className="tag hard" key={constraint.id}>
                      忌 {foodName(constraint.targetId)}
                    </span>
                  ))}
                {member.healthTags.slice(0, 1).map((tag) => (
                  <span className="tag" key={tag}>
                    {HEALTH_TAG_NAMES[tag] ?? tag}
                  </span>
                ))}
              </div>
            </div>
          ))
        )}

        <h3 className="section-label">库存 · 优先消耗</h3>
        {!context ? (
          <p className="empty-state">读取中…</p>
        ) : (
          [
            ...context.inventory.filter((item) => item.priorityConsume),
            ...context.inventory.filter((item) => !item.priorityConsume)
          ]
            .slice(0, 6)
            .map((item) => (
              <div className="inventory-card compact-inv" key={item.id}>
                <strong>{foodName(item.foodId)}</strong>
                {item.priorityConsume ? (
                  <span className="tag priority">优先</span>
                ) : null}
                <div className="muted">
                  {item.quantity.rawExpression}
                  {item.quantity.normalized.estimateG != null
                    ? ` · 约 ${formatGrams(item.quantity.normalized.estimateG)} g`
                    : ""}
                </div>
              </div>
            ))
        )}

        <InventoryImageIntake
          busy={busy}
          confirmationPending={confirmationPending}
          operable={operable}
          onSendToAgent={onSendToAgent}
        />
      </div>
    </aside>
  );
}
