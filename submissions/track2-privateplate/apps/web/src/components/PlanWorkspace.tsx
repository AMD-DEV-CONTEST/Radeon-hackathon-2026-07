import type { MealPlan, UiOnly } from "../api";
import {
  foodName,
  formatGrams,
  formatKcal,
  quantityName,
  shoppingStatusName,
  templateName
} from "../formatters";
import {
  buildPlanDishDisplays,
  planHouseholdNutrition,
  planMemberNutrition,
  planPreparedFoodSummary,
  planQuantitySummary,
  type PlanDishDisplay
} from "../plan-display";
import type { ActionStatus } from "../types";
import { SourceIcon } from "./SourceIcon";

type PlanWorkspaceProps = {
  open: boolean;
  plan: MealPlan | null;
  memberNames: Map<string, string>;
  uiOnly: UiOnly | null;
  orphanedPendingActionId: string | null;
  actionStatus: ActionStatus;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
  onAdjust: () => void;
  onCompleteMeal: () => void;
};

export function PlanWorkspace({
  open,
  plan,
  memberNames,
  uiOnly,
  orphanedPendingActionId,
  actionStatus,
  busy,
  onClose,
  onConfirm,
  onAdjust,
  onCompleteMeal
}: PlanWorkspaceProps) {
  if (!open || (!plan && !uiOnly && !orphanedPendingActionId)) return null;

  const taskCard = uiOnly?.taskCard ?? null;
  const dishes: PlanDishDisplay[] = plan
    ? buildPlanDishDisplays(plan)
    : (taskCard?.menu ?? []).map((item) => ({
        templateId: item.templateId,
        name: item.displayName || templateName(item.templateId),
        role: "",
        coversRoles: [],
        roleLabel: "角色待同步",
        plannedByMember: [],
        plannedTotalG: null,
        preparedTotalG: null
      }));
  const shopping = taskCard?.shoppingItems ?? plan?.shoppingGap.filter((gap) => gap.status !== "not_needed") ?? [];
  const existing = taskCard?.useFromInventory ?? plan?.preparedBatch ?? plan?.batchIngredients ?? [];
  const dinerCount = plan?.dinerIds?.length ?? plan?.memberAllocations.length ?? 0;
  const isPending = Boolean(uiOnly);
  const isOrphaned = Boolean(orphanedPendingActionId && !plan && !uiOnly);
  const isReadyToEat = actionStatus === "ready_to_eat";
  const isEaten = actionStatus === "eaten";
  const confirmLabel = uiOnly?.confirmLabel || "确认安排";
  const subtitle = isPending ? "确认后再发送采购 / 任务" : "确认后再生成采购任务";

  if (isOrphaned) {
    return (
      <aside className="context-drawer" aria-label="本餐方案">
        <header className="drawer-topbar">
          <div>
            <h2>本餐方案</h2>
            <p>确认信息需要重新生成</p>
          </div>
          <div className="drawer-top-actions">
            <span className="drawer-status">需重新生成</span>
            <button className="drawer-collapse" type="button" onClick={onClose}>
              收起
            </button>
            <button className="drawer-icon-button" type="button" onClick={onClose} aria-label="关闭本餐方案">
              <SourceIcon name="x" size={22} />
            </button>
          </div>
        </header>
        <div className="drawer-rule" aria-hidden="true" />
        <div className="drawer-content">
          <p className="drawer-empty">这次待确认安排已失效，请重新生成方案。</p>
          <div className="drawer-actions">
            <button className="drawer-adjust-button" type="button" disabled={busy} onClick={onAdjust}>
              重新生成方案
            </button>
          </div>
          <p className="drawer-footnote">确认信息失效后不会发送任何任务；重新生成前可以继续和我说。</p>
        </div>
      </aside>
    );
  }

  return (
    <aside className="context-drawer" aria-label="本餐方案">
      <header className="drawer-topbar">
        <div>
          <h2>本餐方案</h2>
          <p>{subtitle}</p>
        </div>
        <div className="drawer-top-actions">
          <span className="drawer-status">
            {isPending ? "待确认" : statusLabel(actionStatus)}
          </span>
          <button className="drawer-collapse" type="button" onClick={onClose}>
            收起
          </button>
          <button className="drawer-icon-button" type="button" onClick={onClose} aria-label="关闭本餐方案">
            <SourceIcon name="x" size={22} />
          </button>
        </div>
      </header>

      <div className="drawer-rule" aria-hidden="true" />

      <div className="drawer-content">
        <section className="drawer-menu-section">
          <div className="drawer-section-heading">
            <h3>菜品安排</h3>
            <span>{dishes.length} 道 · 适合 {dinerCount || "家庭"} 人</span>
          </div>
          <div className="drawer-dish-list">
            {dishes.map((dish, index) => (
              <div className="drawer-dish-row" key={dish.templateId}>
                <span className={`drawer-dish-accent accent-${index % 3}`} aria-hidden="true" />
                <div className="drawer-dish-copy">
                  <strong>{dish.name}</strong>
                  <span>{portionSummary(dish, memberNames)}</span>
                  {dish.preparedTotalG != null ? (
                    <small>实际准备 {formatGrams(dish.preparedTotalG)}g</small>
                  ) : null}
                </div>
                <span className="drawer-dish-role">{dish.roleLabel}</span>
              </div>
            ))}
          </div>
        </section>

        {plan ? <PlanFacts plan={plan} memberNames={memberNames} /> : null}

        <div className="drawer-rule" aria-hidden="true" />

        <section className="drawer-shopping-section">
          <div className="drawer-section-heading">
            <h3>采购单</h3>
            <span className="shopping-count">需要补齐 {shopping.length} 项</span>
          </div>
          <div className="drawer-shopping-list">
            {shopping.map((item) => {
              const gap = "foodId" in item ? item : null;
              const foodId = gap?.foodId ?? "";
              const quantity = gap && "purchase" in gap
                ? quantityName(gap.purchase)
                : "purchase" in item
                  ? quantityName(item.purchase)
                  : "数量待确认";
              const status = gap?.status ?? ("status" in item ? item.status : "needed");
              return (
                <div className="drawer-shopping-row" key={foodId}>
                  <span className="shopping-check" aria-hidden="true" />
                  <span className="shopping-name">{foodName(foodId)}</span>
                  <span className="shopping-quantity">{quantity.replace("采购 ", "")}</span>
                  <span className="shopping-status">{shoppingStatusName(status)}</span>
                </div>
              );
            })}
          </div>
        </section>

        <section className="drawer-existing-section">
          <strong>家里已有</strong>
          <span>
            {existing.length > 0
              ? existing.map((item) => foodName(item.foodId)).join(" · ")
              : "当前库存会优先用于本餐"}
          </span>
        </section>

        {isPending ? (
          <div className="drawer-actions">
            <button className="drawer-confirm-button" type="button" disabled={busy} onClick={onConfirm}>
              <SourceIcon name="check" size={18} />
              <span>{confirmLabel}</span>
            </button>
            <button className="drawer-adjust-button" type="button" disabled={busy} onClick={onAdjust}>
              调整方案
            </button>
          </div>
        ) : isReadyToEat ? (
          <div className="drawer-actions">
            <button className="drawer-confirm-button" type="button" disabled={busy} onClick={onCompleteMeal}>
              <SourceIcon name="check" size={18} />
              <span>确认本餐已按计划吃完</span>
            </button>
            <button className="drawer-adjust-button" type="button" disabled={busy} onClick={onAdjust}>
              调整方案
            </button>
          </div>
        ) : isEaten ? (
          <div className="drawer-recorded" role="status">
            <SourceIcon name="check" size={18} />
            <span>本餐已记录</span>
          </div>
        ) : (
          <div className="drawer-actions">
            <button className="drawer-adjust-button" type="button" disabled={busy} onClick={onAdjust}>
              调整方案
            </button>
          </div>
        )}

        {orphanedPendingActionId ? (
          <p className="drawer-expired" role="alert">这次确认已失效，请重新生成方案。</p>
        ) : null}
        <p className="drawer-footnote">确认后抽屉会自动收起；之后可从左侧「本餐状态」再次打开</p>
      </div>
    </aside>
  );
}

function portionSummary(
  dish: PlanDishDisplay,
  memberNames: Map<string, string>,
): string {
  if (dish.plannedByMember.length === 0) {
    return "计划克数暂不可见（旧计划未返回 planned intake）";
  }
  return `计划吃掉 ${formatGrams(dish.plannedTotalG)}g：${dish.plannedByMember
    .map(
      (allocation) =>
        `${memberNames.get(allocation.memberId) ?? "家庭成员"} ${formatGrams(allocation.quantityG)}g`
    )
    .join(" · ")}`;
}

function PlanFacts({
  plan,
  memberNames
}: {
  plan: MealPlan;
  memberNames: Map<string, string>;
}) {
  const quantity = planQuantitySummary(plan);
  const nutrition = planHouseholdNutrition(plan);
  const memberNutrition = planMemberNutrition(plan);
  const preparedFoods = planPreparedFoodSummary(plan);
  const bufferLabel =
    quantity.bufferG != null
      ? `${formatGrams(quantity.bufferG)}g`
      : "未返回";
  const bufferRate =
    plan.prepBuffer != null ? `（${Math.round(plan.prepBuffer * 100)}%）` : "";

  return (
    <section className="drawer-facts" aria-label="本餐计划量与营养">
      <div className="drawer-section-heading">
        <h3>本餐量与营养</h3>
        <span>{plan.prepBuffer != null ? "新合同" : "旧计划兼容"}</span>
      </div>
      <div className="drawer-fact-grid">
        <div className="drawer-fact">
          <span>参与人数</span>
          <strong>{plan.dinerIds?.length ?? plan.memberAllocations.length} 人</strong>
        </div>
        <div className="drawer-fact">
          <span>计划吃掉</span>
          <strong>{quantity.plannedTotalG == null ? "—" : `${formatGrams(quantity.plannedTotalG)}g`}</strong>
        </div>
        <div className="drawer-fact">
          <span>实际准备 / 采购</span>
          <strong>{quantity.preparedTotalG == null ? "—" : `${formatGrams(quantity.preparedTotalG)}g`}</strong>
        </div>
      </div>
      <p className="drawer-buffer-note">
        备餐余量：{bufferLabel}{bufferRate}。只用于烹饪损耗、分量误差和临时变化，不计入已吃量，也不作为剩菜回填库存。
      </p>
      {preparedFoods.length > 0 ? (
        <p className="drawer-prepared-list">
          实际准备食材：
          {preparedFoods
            .map((item) => `${foodName(item.foodId)} ${formatGrams(item.quantityG)}g`)
            .join(" · ")}
        </p>
      ) : null}
      {nutrition ? (
        <div className="drawer-nutrition-summary">
          <strong>全家计划营养</strong>
          <span>{formatKcal(nutrition.energyKcal)} kcal · 蛋白质 {formatGrams(nutrition.proteinG)}g</span>
        </div>
      ) : null}
      <div className="drawer-member-nutrition">
        {memberNutrition.map((member) => (
          <div className="drawer-member-nutrition-row" key={member.memberId}>
            <span>{memberNames.get(member.memberId) ?? "家庭成员"}</span>
            <span>{formatKcal(member.nutrition.energyKcal)} kcal · 蛋白质 {formatGrams(member.nutrition.proteinG)}g</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function statusLabel(status: ActionStatus): string {
  if (status === "plan") return "已规划";
  if (status === "pending") return "待确认";
  if (status === "sent") return "已发送";
  if (status === "ready_to_eat") return "待记录";
  if (status === "eaten") return "已记录";
  return "尚未生成";
}
