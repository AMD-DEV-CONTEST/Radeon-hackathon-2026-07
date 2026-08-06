import { useCallback, useEffect, useMemo, useState } from "react";
import {
  cancelPending,
  completeMealAsPlanned,
  confirmPending,
  fetchAgentSession,
  fetchContext,
  fetchDayContext,
  fetchInbox,
  fetchRuntime,
  humanizeNetworkError,
  resetSession,
  runAgentStream,
  type AgentEvent,
  type HouseholdContext,
  type MealPlan,
  type RuntimeStatus,
  type UiOnly
} from "./api";
import { ConversationPanel } from "./components/ConversationPanel";
import { PlanWorkspace } from "./components/PlanWorkspace";
import { Sidebar, type DrawerTarget } from "./components/Sidebar";
import { UtilityDrawer } from "./components/UtilityDrawer";
import {
  loadConfirmation,
  loadSessionId,
  saveConfirmation
} from "./confirmation-storage";
import { ASSISTANT_PENDING_TEXT } from "./content";
import type { ActionStatus, ChatMessage, InboxSnapshot } from "./types";

function isOperable(runtime: RuntimeStatus | null): boolean {
  if (!runtime) return false;
  if (typeof runtime.operable === "boolean") return runtime.operable;
  return runtime.providerMode === "local_vllm" && runtime.llm?.ready !== false;
}

function isMealPlanConfirmation(uiOnly: UiOnly | null): boolean {
  if (!uiOnly) return false;
  const actionType = uiOnly.actionType;
  return (
    !actionType ||
    actionType === "caregiver_task_send" ||
    actionType === "meal_completion"
  );
}

function confirmationDrawerTarget(uiOnly: UiOnly): DrawerTarget {
  if (uiOnly.actionType === "inventory_restock") return "inventory";
  if (uiOnly.actionType === "member_memory_change") return "members";
  return "plan";
}

function hasPlanWorkspaceData(
  plan: MealPlan | null,
  uiOnly: UiOnly | null,
  orphanedPendingActionId: string | null
): boolean {
  return Boolean(plan || isMealPlanConfirmation(uiOnly) || orphanedPendingActionId);
}

export function App() {
  const [sessionId] = useState(loadSessionId);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [context, setContext] = useState<HouseholdContext | null>(null);
  const [plan, setPlan] = useState<MealPlan | null>(null);
  const [selectedDinerIds, setSelectedDinerIds] = useState<string[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      text: "晚上想吃什么？告诉我几个人、时间和想避开的食材，我来安排。"
    }
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uiOnly, setUiOnly] = useState<UiOnly | null>(() =>
    loadConfirmation(sessionId)
  );
  const [orphanedPendingActionId, setOrphanedPendingActionId] = useState<
    string | null
  >(null);
  const [actionStatus, setActionStatus] = useState<ActionStatus>("idle");
  const [inbox, setInbox] = useState<InboxSnapshot | null>(null);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [drawerTarget, setDrawerTarget] = useState<DrawerTarget | null>(null);
  const [inboxSeen, setInboxSeen] = useState(false);
  /** True only after the user toggles chips; otherwise conversation owns diners. */
  const [dinerChipDirty, setDinerChipDirty] = useState(false);

  const operable = isOperable(runtime);

  const refreshShell = useCallback(async () => {
    const status = await fetchRuntime(sessionId);
    setRuntime(status);
    const [nextContext, session, nextInbox, nextDay] = await Promise.all([
      fetchContext(status.householdId),
      fetchAgentSession(sessionId),
      fetchInbox(),
      fetchDayContext(status.householdId).catch(() => null)
    ]);
    setContext(nextContext);
    setPlan(session.plan);
    const authoritativeDiners =
      session.plan?.dinerIds && session.plan.dinerIds.length > 0
        ? session.plan.dinerIds
        : session.state.dinerIds.length > 0
          ? session.state.dinerIds
          : null;
    setSelectedDinerIds((current) => {
      if (authoritativeDiners) {
        const same =
          current.length === authoritativeDiners.length &&
          authoritativeDiners.every((id) => current.includes(id));
        if (!same) {
          setDinerChipDirty(false);
          return [...authoritativeDiners];
        }
        return current;
      }
      if (current.length > 0) return current;
      setDinerChipDirty(false);
      return nextContext.members.map((member) => member.id);
    });
    setInbox(nextInbox);

    const savedConfirmation = loadConfirmation(sessionId);
    if (
      savedConfirmation &&
      savedConfirmation.pendingActionId === session.state.pendingActionId
    ) {
      setUiOnly(savedConfirmation);
      setOrphanedPendingActionId(null);
      setActionStatus("pending");
      setDrawerTarget(confirmationDrawerTarget(savedConfirmation));
    } else if (session.state.pendingActionId) {
      setUiOnly(null);
      saveConfirmation(sessionId, null);
      setOrphanedPendingActionId(session.state.pendingActionId);
      setActionStatus("pending");
      setDrawerTarget("plan");
    } else if (session.plan) {
      setUiOnly(null);
      saveConfirmation(sessionId, null);
      setOrphanedPendingActionId(null);
      const planDone = nextDay?.completedMeals.some(
        (meal) =>
          meal.planId === session.plan?.id &&
          (meal.planVersion == null || meal.planVersion === session.plan?.version)
      );
      const currentPlanWasSent = nextInbox.items.some(
        (item) =>
          item.plan_id === session.plan?.id &&
          item.plan_version === session.plan?.version
      );
      setActionStatus(
        planDone
          ? "eaten"
          : currentPlanWasSent
            ? "ready_to_eat"
            : "plan"
      );
    } else {
      setUiOnly(null);
      saveConfirmation(sessionId, null);
      setOrphanedPendingActionId(null);
      setActionStatus("idle");
      setDrawerTarget(null);
    }
  }, [sessionId]);

  useEffect(() => {
    refreshShell().catch((requestError: Error) => setError(requestError.message));
    const timer = window.setInterval(() => {
      fetchRuntime(sessionId)
        .then(setRuntime)
        .catch(() => {
          // Keep the last known status; the drawer still works offline.
        });
    }, 8_000);
    return () => window.clearInterval(timer);
  }, [refreshShell, sessionId]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 1100px)");
    const syncRail = () => setRailCollapsed(media.matches);
    syncRail();
    media.addEventListener?.("change", syncRail);
    return () => media.removeEventListener?.("change", syncRail);
  }, []);

  useEffect(() => {
    function closeWithEscape(event: KeyboardEvent): void {
      if (event.key === "Escape") setDrawerTarget(null);
    }
    window.addEventListener("keydown", closeWithEscape);
    return () => window.removeEventListener("keydown", closeWithEscape);
  }, []);

  const memberNames = useMemo(
    () =>
      new Map(
        context?.members.map((member) => [member.id, member.displayName]) ?? []
      ),
    [context]
  );

  const planWorkspaceAvailable = hasPlanWorkspaceData(
    plan,
    uiOnly,
    orphanedPendingActionId
  );

  useEffect(() => {
    if (drawerTarget === "plan" && !planWorkspaceAvailable) {
      setDrawerTarget(null);
    }
  }, [drawerTarget, planWorkspaceAvailable]);

  function toggleDiner(memberId: string): void {
    setSelectedDinerIds((current) => {
      if (!current.includes(memberId)) {
        setError(null);
        setDinerChipDirty(true);
        return [...current, memberId];
      }
      if (current.length === 1) {
        setError("至少保留一位用餐成员。");
        return current;
      }
      setError(null);
      setDinerChipDirty(true);
      return current.filter((id) => id !== memberId);
    });
  }

  function selectNav(target: DrawerTarget | "new"): void {
    if (target === "new") {
      setDrawerTarget(null);
      void onReset();
      return;
    }
    if (target === "inbox") setInboxSeen(true);
    if (target === "plan" && !planWorkspaceAvailable) {
      setDrawerTarget(null);
      window.requestAnimationFrame(() => {
        document.getElementById("meal-request")?.focus();
      });
      return;
    }
    setDrawerTarget(target);
  }

  function openInventoryDrawer(): void {
    setDrawerTarget("inventory");
  }

  function adjustPlan(): void {
    if (uiOnly || orphanedPendingActionId) void onCancel();
    setInput("请调整这份方案：");
    setDrawerTarget(null);
  }

  async function onSend(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy || selectedDinerIds.length === 0) return;
    if (!operable) {
      setError("Agent 还没有准备好，请稍后刷新再试。");
      return;
    }
    setBusy(true);
    setError(null);
    const assistantMessageId = `a-${Date.now()}`;
    setMessages((previous) => [
      ...previous,
      { id: `u-${Date.now()}`, role: "user", text: trimmed },
      {
        id: assistantMessageId,
        role: "assistant",
        text: ASSISTANT_PENDING_TEXT,
        tools: []
      }
    ]);
    setInput("");
    try {
      let failedMessage: string | null = null;
      let planReady = false;
      await runAgentStream({
        sessionId,
        text: trimmed,
        ...(dinerChipDirty ? { dinerIds: selectedDinerIds } : {}),
        onEvent: (event: AgentEvent) => {
          if (event.type === "action_started") {
            setMessages((previous) =>
              previous.map((message) =>
                message.id === assistantMessageId
                  ? {
                      ...message,
                      tools: message.tools?.includes(event.tool)
                        ? message.tools
                        : [...(message.tools ?? []), event.tool]
                    }
                  : message
              )
            );
          }
          if (event.type === "answer_delta") {
            setMessages((previous) =>
              previous.map((message) =>
                message.id === assistantMessageId
                  ? {
                      ...message,
                      text:
                        message.text === ASSISTANT_PENDING_TEXT
                          ? event.text
                          : message.text + event.text
                    }
                  : message
              )
            );
          }
          if (event.type === "plan_ready") {
            planReady = true;
            setActionStatus("plan");
            setMessages((previous) =>
              previous.map((message) =>
                message.id === assistantMessageId
                  ? { ...message, attachPlanPreview: true }
                  : message
              )
            );
          }
          if (event.type === "plan_infeasible") setActionStatus("idle");
          if (event.type === "confirmation_required") {
            const confirmation: UiOnly = {
              pendingActionId: event.pendingActionId,
              confirmationToken: event.confirmationToken,
              payloadHash: event.payloadHash,
              expiresAt: event.expiresAt,
              ...(event.actionType ? { actionType: event.actionType } : {}),
              ...(event.confirmLabel ? { confirmLabel: event.confirmLabel } : {}),
              ...(event.taskCard ? { taskCard: event.taskCard } : {}),
              ...(event.preview ? { preview: event.preview } : {})
            };
            setUiOnly(confirmation);
            setOrphanedPendingActionId(null);
            saveConfirmation(sessionId, confirmation);
            setActionStatus("pending");
            setDrawerTarget(confirmationDrawerTarget(confirmation));
          }
          if (event.type === "run_failed") {
            failedMessage = event.message;
            setMessages((previous) =>
              previous.map((message) =>
                message.id === assistantMessageId &&
                message.text === ASSISTANT_PENDING_TEXT
                  ? { ...message, text: event.message }
                  : message
              )
            );
          }
        }
      });
      if (failedMessage) throw new Error(failedMessage);
      await refreshShell();
      // refreshShell may re-open the confirmation drawer; only force plan when this
      // turn finalized a meal plan and did not create a non-plan confirmation.
      if (planReady) {
        setDrawerTarget((current) =>
          current === "inventory" || current === "members" ? current : "plan"
        );
      }
    } catch (requestError) {
      const message = humanizeNetworkError(requestError);
      setError(message);
      setMessages((previous) =>
        previous.map((item) =>
          item.id === assistantMessageId && item.text === ASSISTANT_PENDING_TEXT
            ? { ...item, text: message }
            : item
        )
      );
    } finally {
      setBusy(false);
    }
  }

  async function onConfirm() {
    if (!uiOnly || busy) return;
    setBusy(true);
    setError(null);
    const actionType = uiOnly.actionType ?? "caregiver_task_send";
    try {
      const result = await confirmPending({
        sessionId,
        pendingActionId: uiOnly.pendingActionId,
        confirmationToken: uiOnly.confirmationToken,
        idempotencyKey: `web-${uiOnly.pendingActionId}`,
        expectedPayloadHash: uiOnly.payloadHash
      });
      const replayed = Boolean(
        result && typeof result === "object" && "receipt" in result
          ? (result as { receipt: { replayed: boolean } }).receipt.replayed
          : false
      );
      const systemText =
        actionType === "inventory_restock"
          ? replayed
            ? "这次入库已经记录过了，没有重复增加。"
            : "已确认入库，下一轮对话会用到更新后的库存。"
          : actionType === "member_memory_change"
            ? replayed
              ? "这项家庭资料已经保存过了。"
              : "已保存家庭资料，下一轮对话会记住这项偏好。"
            : replayed
              ? "这份安排已经确认过了。"
              : "已确认本餐安排，采购清单已放入模拟信箱。";
      setMessages((previous) => [
        ...previous,
        { id: `confirm-${Date.now()}`, role: "system", text: systemText }
      ]);
      setUiOnly(null);
      setOrphanedPendingActionId(null);
      saveConfirmation(sessionId, null);
      setDrawerTarget(null);
      if (actionType === "caregiver_task_send" || uiOnly.taskCard) {
        setActionStatus("ready_to_eat");
      } else if (plan) {
        setActionStatus("plan");
      } else {
        setActionStatus("idle");
      }
      await refreshShell();
    } catch (requestError) {
      setError(humanizeNetworkError(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function onCancel() {
    const pendingActionId = uiOnly?.pendingActionId ?? orphanedPendingActionId;
    if (!pendingActionId || busy) return;
    const actionType = uiOnly?.actionType;
    setBusy(true);
    setError(null);
    try {
      await cancelPending(sessionId, pendingActionId);
      setUiOnly(null);
      setOrphanedPendingActionId(null);
      saveConfirmation(sessionId, null);
      setActionStatus(plan ? "plan" : "idle");
      setDrawerTarget(null);
      const cancelText =
        actionType === "inventory_restock"
          ? "已取消这次入库预览，库存未改动。"
          : actionType === "member_memory_change"
            ? "已取消这次家庭资料预览，记忆未改动。"
            : "已取消这次待确认安排，计划仍保留，尚未发送。";
      setMessages((previous) => [
        ...previous,
        {
          id: `cancel-${Date.now()}`,
          role: "system",
          text: cancelText
        }
      ]);
    } catch (requestError) {
      setError(humanizeNetworkError(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function onReset() {
    setBusy(true);
    setError(null);
    try {
      await resetSession();
      setPlan(null);
      setUiOnly(null);
      setOrphanedPendingActionId(null);
      saveConfirmation(sessionId, null);
      setSelectedDinerIds([]);
      setDinerChipDirty(false);
      setActionStatus("idle");
      setDrawerTarget(null);
      setMessages([
        {
          id: "reset",
          role: "assistant",
          text: "新对话已开始。家庭记忆和库存仍保留，我们可以重新安排这一餐。"
        }
      ]);
      await refreshShell();
    } catch (requestError) {
      setError(humanizeNetworkError(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function onCompleteMeal() {
    if (!plan || !runtime || busy) return;
    setBusy(true);
    setError(null);
    try {
      await completeMealAsPlanned({
        householdId: runtime.householdId,
        planId: plan.id
      });
      setMessages((previous) => [
        ...previous,
        {
          id: `meal-done-${Date.now()}`,
          role: "system",
          text: "已记录本餐，下一次规划会参考新的剩余额度与库存。"
        }
      ]);
      setActionStatus("eaten");
      setDrawerTarget(null);
      await refreshShell();
    } catch (requestError) {
      setError(humanizeNetworkError(requestError));
    } finally {
      setBusy(false);
    }
  }

  const utilityView =
    drawerTarget && drawerTarget !== "plan" ? drawerTarget : null;

  return (
    <div className={`app product-app ${drawerTarget ? "drawer-open" : ""}`} aria-busy={busy}>
      <Sidebar
        collapsed={railCollapsed}
        busy={busy}
        activeTarget={drawerTarget}
        actionStatus={actionStatus}
        inbox={inbox}
        inboxSeen={inboxSeen}
        onToggle={() => setRailCollapsed((current) => !current)}
        onSelect={selectNav}
      />

      <main className="main-stage">
        {error ? (
          <div className="error-banner" role="alert" aria-live="assertive">
            {error}
          </div>
        ) : null}
        <ConversationPanel
          messages={messages}
          actionStatus={actionStatus}
          input={input}
          busy={busy}
          operable={operable}
          selectedDinerIds={selectedDinerIds}
          members={context?.members ?? []}
          plan={plan}
          memberLookup={memberNames}
          confirmationPending={Boolean(uiOnly)}
          onInputChange={setInput}
          onToggleDiner={toggleDiner}
          onOpenInventory={openInventoryDrawer}
          onSend={(text) => void onSend(text)}
        />
      </main>

      {drawerTarget === "plan" && planWorkspaceAvailable ? (
        <PlanWorkspace
          open
          plan={plan}
          memberNames={memberNames}
          uiOnly={isMealPlanConfirmation(uiOnly) ? uiOnly : null}
          orphanedPendingActionId={orphanedPendingActionId}
          actionStatus={actionStatus}
          busy={busy}
          onClose={() => setDrawerTarget(null)}
          onConfirm={() => void onConfirm()}
          onAdjust={adjustPlan}
          onCompleteMeal={() => void onCompleteMeal()}
        />
      ) : null}
      {utilityView ? (
        <UtilityDrawer
          view={utilityView}
          context={context}
          inbox={inbox}
          busy={busy}
          confirmationPending={Boolean(uiOnly)}
          operable={operable}
          uiOnly={uiOnly}
          onClose={() => setDrawerTarget(null)}
          onRefresh={() => void refreshShell()}
          onSendToAgent={(text) => void onSend(text)}
          onConfirm={() => void onConfirm()}
          onCancelPending={() => void onCancel()}
        />
      ) : null}
    </div>
  );
}
