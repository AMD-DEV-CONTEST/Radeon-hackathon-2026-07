import { logAudit } from "./audit";
import { sendFeishuNotification } from "./feishu";

export async function reportCronFailure(name: string, error: unknown): Promise<void> {
  const message = error instanceof Error ? error.message : String(error);
  await logAudit({
    action: "admin_action",
    resource_type: "cron",
    resource_id: name,
    detail: { status: "failed", error: message.slice(0, 500) },
    correlation_id: `cron_${name}`,
  });

  sendFeishuNotification({
    header: { title: { tag: "plain_text", content: `Cron 任务失败：${name}` }, template: "red" },
    elements: [{ tag: "div", text: { tag: "lark_md", content: `**任务**：${name}\n**错误**：${message.slice(0, 500)}` } }],
  }).catch(() => {});
}
