import type { DayContext, MealPlan } from "../api";
import {
  foodName,
  formatGrams,
  formatKcal,
  mealRoleName,
  memberName,
  templateName
} from "../formatters";
import { planHouseholdNutrition, planQuantitySummary } from "../plan-display";
import type { ActionStatus, InboxSnapshot } from "../types";

type MealStatusBarProps = {
  plan: MealPlan | null;
  dayContext: DayContext | null;
  actionStatus: ActionStatus;
  inbox: InboxSnapshot | null;
  busy: boolean;
  memberNames: Map<string, string>;
  onCompleteMeal: () => void;
};

function planAlreadyCompleted(
  plan: MealPlan | null,
  dayContext: DayContext | null
): boolean {
  if (!plan || !dayContext) return false;
  return dayContext.completedMeals.some(
    (meal) =>
      meal.planId === plan.id &&
      (meal.planVersion == null || meal.planVersion === plan.version)
  );
}

export function MealStatusBar({
  plan,
  dayContext,
  actionStatus,
  inbox,
  busy,
  memberNames,
  onCompleteMeal
}: MealStatusBarProps) {
  if (!plan) return null;

  const eaten = planAlreadyCompleted(plan, dayContext);
  const taskSent =
    eaten ||
    actionStatus === "ready_to_eat" ||
    actionStatus === "sent" ||
    actionStatus === "eaten" ||
    Boolean(
      inbox?.items.some(
        (item) =>
          item.plan_id === plan.id && item.plan_version === plan.version
      )
    );

  // Only show after plan exists; emphasize after task send or when ready to log meal.
  if (!taskSent && actionStatus !== "plan" && actionStatus !== "pending") {
    return null;
  }

  const stage = eaten
    ? "eaten"
    : taskSent
      ? "ready_to_eat"
      : actionStatus === "pending"
        ? "pending"
        : "plan";

  const title =
    stage === "eaten"
      ? "本餐已记录"
      : stage === "ready_to_eat"
        ? "采购/任务已就绪 · 待确认吃完"
        : stage === "pending"
          ? "本餐计划 · 等待确认发送"
          : "本餐计划已生成";

  return (
    <section
      className={`meal-status-bar stage-${stage}`}
      role="region"
      aria-label="本餐状态"
    >
      <div className="meal-status-head">
        <div>
          <strong>{title}</strong>
          <span className="muted">
            {" "}
            菜单 v{plan.version}
            {plan.mealType === "lunch"
              ? " · 午餐"
              : plan.mealType === "dinner"
                ? " · 晚餐"
                : ""}
          </span>
        </div>
        <span className={`pill meal-stage-pill ${stage}`}>
          {stage === "eaten" && "已吃完"}
          {stage === "ready_to_eat" && "可确认吃完"}
          {stage === "pending" && "待发送"}
          {stage === "plan" && "已规划"}
        </span>
      </div>

      <div className="meal-status-body">
        <div className="meal-food-list">
          <div className="meal-food-label">本餐食物列表</div>
          <ul className="menu-list compact">
            {plan.sharedTemplates.map((template) => (
              <li key={template.templateId}>
                <strong>{template.name || templateName(template.templateId)}</strong>
                <span className="muted">
                  · {(template.coversRoles ?? [template.role])
                    .map((role) => mealRoleName(role))
                    .join(" · ")}
                </span>
              </li>
            ))}
          </ul>
          {plan.preparedBatch?.length || plan.batchIngredients?.length ? (
            <p className="muted compact-line meal-ingredients">
              实际准备/采购：
              {(plan.preparedBatch ?? plan.batchIngredients ?? [])
                .slice(0, 8)
                .map(
                  (item) =>
                    `${foodName(item.foodId)} ${
                      item.quantityG != null
                        ? `${formatGrams(item.quantityG)}g`
                        : ""
                    }`.trim()
                )
                .join("、")}
              {(plan.preparedBatch ?? plan.batchIngredients ?? []).length > 8 ? "…" : ""}
            </p>
          ) : null}
          <PlanQuantityLine plan={plan} />
          {plan.dinerIds && plan.dinerIds.length > 0 ? (
            <p className="muted compact-line">
              用餐人：
              {plan.dinerIds
                .map((id) => memberNames.get(id) ?? memberName(id))
                .join("、")}
            </p>
          ) : null}
        </div>

        <div className="meal-status-actions">
          {stage === "ready_to_eat" ? (
            <>
              <p className="meal-status-hint">
                采购/任务已保存。按计划做完并吃完后，点一次确认即可写入今日账本；之后模型会读到新的剩余额度与库存。
              </p>
              <button
                type="button"
                className="primary meal-complete-btn"
                disabled={busy}
                onClick={onCompleteMeal}
              >
                确认本餐已按计划吃完
              </button>
            </>
          ) : stage === "eaten" ? (
            <p className="meal-status-hint ok-text">
              本餐已记入 completed meals。新对话 / 下一次规划会使用更新后的剩余额度。
            </p>
          ) : stage === "pending" ? (
            <p className="meal-status-hint">
              请先确认发送任务卡/采购清单；发送成功后这里会出现「确认吃完」按钮。
            </p>
          ) : (
            <>
              <p className="meal-status-hint">
                可继续改菜单，或说「发给保姆」生成采购/任务。若已自己做完，也可直接确认吃完。
              </p>
              <button
                type="button"
                className="meal-complete-btn secondary-complete"
                disabled={busy}
                onClick={onCompleteMeal}
              >
                确认本餐已按计划吃完
              </button>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function PlanQuantityLine({ plan }: { plan: MealPlan }) {
  const quantity = planQuantitySummary(plan);
  const nutrition = planHouseholdNutrition(plan);
  if (quantity.plannedTotalG == null && quantity.preparedTotalG == null && !nutrition) {
    return null;
  }
  return (
    <p className="muted compact-line meal-quantity-line">
      计划吃掉 {quantity.plannedTotalG == null ? "—" : `${formatGrams(quantity.plannedTotalG)}g`}
      {" · "}
      实际准备 {quantity.preparedTotalG == null ? "—" : `${formatGrams(quantity.preparedTotalG)}g`}
      {nutrition ? ` · 全家 ${formatKcal(nutrition.energyKcal)} kcal · 蛋白质 ${formatGrams(nutrition.proteinG)}g` : ""}
    </p>
  );
}
