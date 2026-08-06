import type { HouseholdContext, UiOnly } from "../api";
import {
  foodName,
  formatGrams,
  HEALTH_TAG_NAMES,
  ROLE_NAMES
} from "../formatters";
import type { InboxSnapshot } from "../types";
import type { DrawerTarget } from "./Sidebar";
import { InventoryImageIntake } from "./InventoryImageIntake";
import { SourceIcon } from "./SourceIcon";

type UtilityView = Exclude<DrawerTarget, "plan">;

type UtilityDrawerProps = {
  view: UtilityView;
  context: HouseholdContext | null;
  inbox: InboxSnapshot | null;
  busy: boolean;
  confirmationPending: boolean;
  operable: boolean;
  uiOnly: UiOnly | null;
  onClose: () => void;
  onRefresh: () => void;
  onSendToAgent: (text: string) => void;
  onConfirm: () => void;
  onCancelPending: () => void;
};

export function UtilityDrawer({
  view,
  context,
  inbox,
  busy,
  confirmationPending,
  operable,
  uiOnly,
  onClose,
  onRefresh,
  onSendToAgent,
  onConfirm,
  onCancelPending
}: UtilityDrawerProps) {
  return (
    <aside className="utility-drawer" aria-label={viewTitle(view)}>
      <div className="drawer-header">
        <div>
          <p className="eyebrow">家庭空间</p>
          <h2>{viewTitle(view)}</h2>
        </div>
        <button className="drawer-close" type="button" onClick={onClose}>
          收起
        </button>
      </div>

      <div className="drawer-scroll">
        {view === "members" ? (
          <MembersView
            context={context}
            uiOnly={uiOnly}
            busy={busy}
            onConfirm={onConfirm}
            onCancelPending={onCancelPending}
          />
        ) : null}
        {view === "inventory" ? (
          <InventoryView
            context={context}
            busy={busy}
            confirmationPending={confirmationPending}
            operable={operable}
            uiOnly={uiOnly}
            onSendToAgent={onSendToAgent}
            onConfirm={onConfirm}
            onCancelPending={onCancelPending}
          />
        ) : null}
        {view === "inbox" ? <InboxView inbox={inbox} /> : null}
        {view === "settings" ? <SettingsView onRefresh={onRefresh} /> : null}
      </div>
    </aside>
  );
}

function MembersView({
  context,
  uiOnly,
  busy,
  onConfirm,
  onCancelPending
}: {
  context: HouseholdContext | null;
  uiOnly: UiOnly | null;
  busy: boolean;
  onConfirm: () => void;
  onCancelPending: () => void;
}) {
  const memoryPreview =
    uiOnly?.actionType === "member_memory_change" ? uiOnly : null;

  if ((!context || context.members.length === 0) && !memoryPreview) {
    return <EmptyDrawerState text="还没有家庭成员资料。" />;
  }

  return (
    <div className="utility-content">
      {memoryPreview ? (
        <MemberMemoryPreviewCard
          uiOnly={memoryPreview}
          busy={busy}
          onConfirm={onConfirm}
          onCancelPending={onCancelPending}
        />
      ) : null}
      <p className="drawer-intro">
        这里保存每个人的用餐偏好。需要安排本餐时，可以直接在对话上方选择成员。
      </p>
      {context && context.members.length > 0 ? (
        <div className="member-detail-list">
          {context.members.map((member) => (
            <article className="member-detail" key={member.id}>
              <div className="member-detail-avatar">
                {member.displayName.slice(0, 1)}
              </div>
              <div className="member-detail-main">
                <div className="member-detail-title">
                  <strong>{member.displayName}</strong>
                  <span>{ROLE_NAMES[member.roleLabel] ?? "家庭成员"}</span>
                </div>
                {member.healthTags.length > 0 ? (
                  <div className="tag-row">
                    {member.healthTags.map((tag) => (
                      <span className="soft-tag" key={tag}>
                        {HEALTH_TAG_NAMES[tag] ?? tag}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="muted compact-line">暂无特别关注</span>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function InventoryView({
  context,
  busy,
  confirmationPending,
  operable,
  uiOnly,
  onSendToAgent,
  onConfirm,
  onCancelPending
}: {
  context: HouseholdContext | null;
  busy: boolean;
  confirmationPending: boolean;
  operable: boolean;
  uiOnly: UiOnly | null;
  onSendToAgent: (text: string) => void;
  onConfirm: () => void;
  onCancelPending: () => void;
}) {
  const inventory = context?.inventory ?? [];
  const restockPreview =
    uiOnly?.actionType === "inventory_restock" ? uiOnly : null;

  return (
    <div className="utility-content">
      {restockPreview ? (
        <InventoryRestockPreviewCard
          uiOnly={restockPreview}
          busy={busy}
          onConfirm={onConfirm}
          onCancelPending={onCancelPending}
        />
      ) : (
        <p className="drawer-intro">
          只在打开库存时查看详情；本餐规划会优先考虑快到期和需要优先消耗的食材。
        </p>
      )}
      {inventory.length > 0 ? (
        <div className="inventory-detail-list">
          {inventory.map((item) => (
            <div className="inventory-detail-row" key={item.id}>
              <div>
                <strong>{foodName(item.foodId)}</strong>
                {item.priorityConsume ? (
                  <span className="soft-tag accent-tag">优先吃</span>
                ) : null}
              </div>
              <span className="muted">
                {item.quantity.normalized.estimateG != null
                  ? `${formatGrams(item.quantity.normalized.estimateG)} g`
                  : item.quantity.rawExpression}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <EmptyDrawerState text="当前还没有可用库存。" />
      )}
      <InventoryImageIntake
        busy={busy}
        confirmationPending={confirmationPending}
        operable={operable}
        onSendToAgent={onSendToAgent}
      />
    </div>
  );
}

function InventoryRestockPreviewCard({
  uiOnly,
  busy,
  onConfirm,
  onCancelPending
}: {
  uiOnly: UiOnly;
  busy: boolean;
  onConfirm: () => void;
  onCancelPending: () => void;
}) {
  const preview = asRecord(uiOnly.preview);
  const foodId = stringField(preview, "foodId");
  const label =
    stringField(preview, "foodName") ||
    (foodId ? foodName(foodId) : "食材");
  const rawExpression = stringField(preview, "rawExpression");
  const deltaG = numberField(preview, "deltaG");
  const beforeG = numberField(preview, "beforeEstimateG");
  const afterG = numberField(preview, "afterEstimateG");
  const note = stringField(preview, "note") || "确认入库前不会修改库存。";
  const confirmLabel = uiOnly.confirmLabel || "确认入库";

  return (
    <section className="inventory-preview-card" aria-label="入库预览">
      <div className="inventory-preview-head">
        <div>
          <strong>入库预览</strong>
          <span className="soft-tag accent-tag">待确认</span>
        </div>
        <p className="muted compact-line">{note}</p>
      </div>
      <div className="inventory-preview-item">
        <strong>{label}</strong>
        <span>{rawExpression || "数量见下方变化"}</span>
      </div>
      <div className="inventory-preview-facts">
        <div>
          <span>确认前</span>
          <strong>{beforeG == null ? "—" : `${formatGrams(beforeG)}g`}</strong>
        </div>
        <div>
          <span>确认后</span>
          <strong>{afterG == null ? "—" : `${formatGrams(afterG)}g`}</strong>
        </div>
        <div>
          <span>增量</span>
          <strong>{deltaG == null ? "—" : `+${formatGrams(deltaG)}g`}</strong>
        </div>
      </div>
      <div className="inventory-preview-actions">
        <button
          className="drawer-confirm-button"
          type="button"
          disabled={busy}
          onClick={onConfirm}
        >
          <SourceIcon name="check" size={18} />
          <span>{confirmLabel}</span>
        </button>
        <button
          className="drawer-adjust-button"
          type="button"
          disabled={busy}
          onClick={onCancelPending}
        >
          先不写入
        </button>
      </div>
      <p className="muted compact-line">
        下方列表仍是当前真实库存；只有点确认后数字才会变化。
      </p>
    </section>
  );
}

function MemberMemoryPreviewCard({
  uiOnly,
  busy,
  onConfirm,
  onCancelPending
}: {
  uiOnly: UiOnly;
  busy: boolean;
  onConfirm: () => void;
  onCancelPending: () => void;
}) {
  const preview = asRecord(uiOnly.preview);
  const memberName = stringField(preview, "memberName") || "家庭成员";
  const kind = stringField(preview, "kind");
  const summary = stringField(preview, "summary") || "资料变更";
  const polarity = stringField(preview, "polarity");
  const note = stringField(preview, "note") || "确认保存前不会改写家庭资料。";
  const confirmLabel = uiOnly.confirmLabel || "确认保存家庭资料";
  const kindLabel =
    kind === "health_fact" ? "健康资料" : kind === "preference" ? "偏好" : "家庭资料";

  return (
    <section className="inventory-preview-card" aria-label="家庭资料预览">
      <div className="inventory-preview-head">
        <div>
          <strong>资料预览</strong>
          <span className="soft-tag accent-tag">待确认</span>
        </div>
        <p className="muted compact-line">{note}</p>
      </div>
      <div className="inventory-preview-item">
        <strong>{memberName} · {kindLabel}</strong>
        <span>{summary}</span>
        {polarity ? <span>极性：{polarity}</span> : null}
      </div>
      <div className="inventory-preview-actions">
        <button
          className="drawer-confirm-button"
          type="button"
          disabled={busy}
          onClick={onConfirm}
        >
          <SourceIcon name="check" size={18} />
          <span>{confirmLabel}</span>
        </button>
        <button
          className="drawer-adjust-button"
          type="button"
          disabled={busy}
          onClick={onCancelPending}
        >
          取消
        </button>
      </div>
    </section>
  );
}

function InboxView({ inbox }: { inbox: InboxSnapshot | null }) {
  const items = inbox?.items ?? [];

  return (
    <div className="utility-content">
      <div className="inbox-intro-card">
        <span className="inbox-mark" aria-hidden="true" />
        <div>
          <strong>模拟收件箱</strong>
          <p>这里只展示等待家庭执行的示例任务，不会真实发送消息。</p>
        </div>
      </div>
      {items.length === 0 ? (
        <EmptyDrawerState text="确认本餐安排后，任务会出现在这里。" />
      ) : (
        <div className="inbox-detail-list">
          {items.map((item) => (
            <article className="inbox-detail-item" key={item.id}>
              <div className="inbox-item-topline">
                <strong>{item.recipient_label}</strong>
                <span className="soft-tag">
                  {item.status === "sent" ? "待执行" : item.status}
                </span>
              </div>
              <p>
                {item.taskCard.menu.map((menuItem) => menuItem.displayName).join("、")}
              </p>
              {item.taskCard.shoppingItems.length > 0 ? (
                <div className="inbox-shopping-note">
                  采购 {item.taskCard.shoppingItems.map((shoppingItem) => foodName(shoppingItem.foodId)).join("、")}
                </div>
              ) : (
                <div className="inbox-shopping-note">无需额外采购</div>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

function SettingsView({ onRefresh }: { onRefresh: () => void }) {
  return (
    <div className="utility-content settings-content">
      <p className="drawer-intro">
        PrivatePlate 会把家庭记忆、库存和当前对话分开保存，让每次规划都能接着上次继续。
      </p>
      <div className="settings-list">
        <div className="settings-row">
          <div>
            <strong>家庭空间</strong>
            <span>小林一家</span>
          </div>
          <span className="settings-state">已连接</span>
        </div>
        <div className="settings-row">
          <div>
            <strong>安全确认</strong>
            <span>发送前始终需要你确认</span>
          </div>
          <span className="settings-state is-on">开启</span>
        </div>
      </div>
      <button className="secondary drawer-refresh-button" type="button" onClick={onRefresh}>
        刷新家庭状态
      </button>
    </div>
  );
}

function EmptyDrawerState({ text }: { text: string }) {
  return <p className="drawer-empty">{text}</p>;
}

function viewTitle(view: UtilityView): string {
  if (view === "members") return "家庭成员";
  if (view === "inventory") return "库存";
  if (view === "inbox") return "模拟信箱";
  return "设置";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringField(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === "string" ? value : "";
}

function numberField(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
