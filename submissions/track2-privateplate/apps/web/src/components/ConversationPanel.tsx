import { useEffect, useRef, type FormEvent, type KeyboardEvent } from "react";
import type { MealPlan } from "../api";
import {
  CHAT_ROLE_NAMES,
  formatGrams,
  humanizeProductText,
  prepareChatAnswer,
  templateName
} from "../formatters";
import { buildPlanDishDisplays } from "../plan-display";
import type { ActionStatus, ChatMessage } from "../types";
import { localMealHero } from "../content";
import { SourceIcon } from "./SourceIcon";
import { VoiceInputButton } from "./VoiceInputButton";

type ConversationPanelProps = {
  messages: ChatMessage[];
  actionStatus: ActionStatus;
  input: string;
  busy: boolean;
  operable: boolean;
  selectedDinerIds: string[];
  members: Array<{ id: string; displayName: string }>;
  plan: MealPlan | null;
  memberLookup: Map<string, string>;
  confirmationPending: boolean;
  onInputChange: (value: string) => void;
  onToggleDiner: (memberId: string) => void;
  onOpenInventory: () => void;
  onSend: (text: string) => void;
};

export function ConversationPanel({
  messages,
  actionStatus,
  input,
  busy,
  operable,
  selectedDinerIds,
  members,
  plan,
  memberLookup,
  confirmationPending,
  onInputChange,
  onToggleDiner,
  onOpenInventory,
  onSend
}: ConversationPanelProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputDisabled = busy || !operable;
  // Keep multi-turn history visible. Messages are appended in App state;
  // only hide system notices, do not collapse turns into the latest pair.
  const visibleMessages = messages.filter((message) => message.role !== "system");
  const hero = localMealHero();
  const placeholder = composerPlaceholder({
    hasPlan: Boolean(plan),
    actionStatus,
    confirmationPending
  });

  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages.length]);

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!inputDisabled && input.trim() && selectedDinerIds.length > 0) {
      onSend(input);
    }
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    if (!inputDisabled && input.trim() && selectedDinerIds.length > 0) {
      onSend(input);
    }
  }

  return (
    <section className="chat-panel" aria-label="PrivatePlate Agent 对话">
      <header className="chat-header">
        <div className="chat-head-copy">
          <p className="chat-kicker">{hero.kicker}</p>
          <h1>{hero.headline}</h1>
        </div>
        <div className="member-picker" aria-label="本次就餐成员">
          <span className="member-picker-label">这次一起吃饭</span>
          <div className="member-chip-list">
            {members.slice(0, 3).map((member) => {
              const selected = selectedDinerIds.includes(member.id);
              return (
                <button
                  className={`member-chip ${selected ? "selected" : ""}`}
                  type="button"
                  key={member.id}
                  aria-pressed={selected}
                  onClick={() => onToggleDiner(member.id)}
                >
                  {member.displayName}
                </button>
              );
            })}
            {members.length > 3 ? (
              <span className="member-chip more-chip">+ {members.length - 3} 位</span>
            ) : null}
          </div>
        </div>
      </header>

      <div className="chat-divider" aria-hidden="true" />

      <div
        className="chat-scroll"
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="对话记录"
      >
        <div className="chat-content">
          <div className="messages">
            {visibleMessages.map((message) => {
              const showPlanPreview = Boolean(
                message.role === "assistant" && message.attachPlanPreview && plan
              );
              const displayText =
                message.role === "assistant" && showPlanPreview
                  ? message.text ===
                      "晚上想吃什么？告诉我几个人、时间和想避开的食材，我来安排。"
                    ? planSummary(plan!)
                    : compactAssistantAnswer(message.text, memberLookup)
                  : prepareChatAnswer(message.text, {
                      memberLookup,
                      hasPlan: showPlanPreview,
                      compact: true
                    });
              const assistantMeta = showPlanPreview
                ? "PrivatePlate  ·  已根据今天的状态排好"
                : message.role === "assistant"
                  ? "PrivatePlate  ·  刚刚"
                  : `${CHAT_ROLE_NAMES[message.role]} · 刚刚`;
              return (
                <article className={`message ${message.role}`} key={message.id}>
                  <div className="message-meta">
                    <span className="message-avatar" aria-hidden="true">
                      {message.role === "assistant" ? (
                        <SourceIcon name="plate" size={20} />
                      ) : message.role === "user" ? (
                        "你"
                      ) : (
                        "·"
                      )}
                    </span>
                    <span>{assistantMeta}</span>
                  </div>
                  <div className="message-body">{displayText}</div>
                  {showPlanPreview ? <PlanMessage plan={plan!} /> : null}
                </article>
              );
            })}
          </div>
        </div>
      </div>

      <form className="composer" onSubmit={submit}>
        <p className="composer-label">继续和我说</p>
        <div className="composer-box">
          <textarea
            id="meal-request"
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            onKeyDown={onComposerKeyDown}
            placeholder={placeholder}
            aria-label="输入本餐需求"
            disabled={inputDisabled}
            rows={1}
          />
          <div className="composer-toolbar">
            <div className="composer-tools">
              <button
                className="composer-icon"
                type="button"
                disabled={busy}
                onClick={onOpenInventory}
                aria-label="添加库存信息"
                title="添加库存信息"
              >
                <SourceIcon name="paperclip" size={18} />
              </button>
              <VoiceInputButton
                disabled={busy}
                onTranscript={onInputChange}
              />
              <span className="voice-note">语音会先转成文字，不会自动发送</span>
            </div>
            <button
              className="send-button"
              type="submit"
              disabled={inputDisabled || !input.trim() || selectedDinerIds.length === 0}
              aria-label="发送消息"
            >
              <SourceIcon name="arrowUp" size={18} />
            </button>
          </div>
        </div>
        <p className="composer-hint">Enter 发送  ·  Shift + Enter 换行</p>
      </form>
    </section>
  );
}

function PlanMessage({ plan }: { plan: MealPlan }) {
  const dishes = buildPlanDishDisplays(plan);
  return (
    <div className="chat-plan-preview">
      {dishes.map((dish, index) => (
        <div className="chat-dish-row" key={dish.templateId}>
          <span className={`dish-dot dish-dot-${index % 3}`} aria-hidden="true" />
          <span className="dish-role">{dish.roleLabel}</span>
          <strong>{dish.name || templateName(dish.templateId)}</strong>
          <span className="dish-time">
            {dish.plannedTotalG == null
              ? "克数见右侧"
              : `计划 ${formatGrams(dish.plannedTotalG)}g`}
          </span>
        </div>
      ))}
      <p className="chat-plan-note">
        每道菜的计划摄入克数、全家营养和实际准备/采购量都在右侧。
        <br />
        确认后，我再帮你生成采购任务。
      </p>
      <p className="chat-time">刚刚</p>
    </div>
  );
}

function planSummary(plan: MealPlan): string {
  const dinerCount = plan.dinerIds?.length ?? plan.memberAllocations.length;
  const dinerLabel = dinerCount === 3 ? "三个人" : `${dinerCount || "家庭"} 位成员`;
  return `可以。我为${dinerLabel}排好了 ${plan.sharedTemplates.length} 道菜，\n并按今天的预算计算了真实计划克数。`;
}

function composerPlaceholder(input: {
  hasPlan: boolean;
  actionStatus: ActionStatus;
  confirmationPending: boolean;
}): string {
  if (input.confirmationPending) {
    return "点抽屉里的确认，或继续补充要求。";
  }
  if (!input.hasPlan || input.actionStatus === "idle") {
    return "说说几个人吃饭、想避开什么，我来安排这一餐。";
  }
  if (input.actionStatus === "ready_to_eat" || input.actionStatus === "sent") {
    return "还能改菜单；做完后可在本餐状态里确认吃完。";
  }
  if (input.actionStatus === "eaten") {
    return "本餐已记录。还可以查库存，或重新安排下一餐。";
  }
  return "想换哪道菜直接说，或说「发给保姆」。";
}

function compactAssistantAnswer(
  text: string,
  memberLookup: Map<string, string>
): string {
  const lines = humanizeProductText(text, memberLookup)
    .replaceAll("**", "")
    .split(/\n+/)
    .map((line) => line.replace(/^[-*#>\s]+/, "").trim())
    .filter((line) => line && !/^schema_version|toolTrace|effectiveArguments/i.test(line));
  const primary = lines[0] ?? "已生成本餐安排。";
  return `${primary}\n详情和采购清单已放在右侧。`;
}
