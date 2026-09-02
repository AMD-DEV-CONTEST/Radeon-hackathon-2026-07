import { MessageCircle, AlertCircle } from "lucide-react";

export default function ConversationBubbles({
  conversation,
}: {
  conversation: string | any[] | null | undefined;
}) {
  if (!conversation) {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-muted-foreground/40">
        <MessageCircle className="h-9 w-9 mb-2" strokeWidth={1.2} />
        <p className="text-sm text-muted-foreground">暂无对话记录</p>
      </div>
    );
  }

  let messages: any[] = [];
  try {
    if (Array.isArray(conversation)) {
      messages = conversation;
    } else if (typeof conversation === "string") {
      const trimmed = conversation.trim();
      if (trimmed.startsWith("[")) {
        const parsed = JSON.parse(trimmed);
        messages = Array.isArray(parsed) ? parsed : [];
      } else {
        messages = trimmed.split("\n").filter((l) => l.trim());
      }
    }

    if (!Array.isArray(messages)) messages = [];
  } catch {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-muted-foreground/40">
        <AlertCircle className="h-9 w-9 mb-2" strokeWidth={1.2} />
        <p className="text-sm text-muted-foreground">对话数据格式异常</p>
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-muted-foreground/40">
        <MessageCircle className="h-9 w-9 mb-2" strokeWidth={1.2} />
        <p className="text-sm text-muted-foreground">对话数据为空</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-4 bg-muted/40 rounded-xl max-h-[400px] overflow-y-auto overflow-x-hidden">
      {messages.map((msg, idx) => {
        const rawText = typeof msg === "string" ? msg : msg.content || "";
        const roleField = typeof msg === "object" && msg.role ? String(msg.role) : "";

        const isBot =
          roleField === "bot" ||
          roleField === "机器人" ||
          roleField === "assistant" ||
          rawText.startsWith("机器人") ||
          rawText.startsWith("客服") ||
          rawText.startsWith("卖家");

        const isCustomer =
          roleField === "user" ||
          roleField === "customer" ||
          rawText.startsWith("顾客") ||
          rawText.startsWith("客户") ||
          rawText.startsWith("买家") ||
          rawText.startsWith("用户");

        const cleanText = rawText.replace(/^(顾客|客户|买家|用户|客服|机器人|卖家)[：:]\s*/, "");

        const side: "left" | "right" =
          isBot ? "right" : isCustomer ? "left" : idx % 2 === 0 ? "left" : "right";

        const senderLabel = isBot ? "机器人" : isCustomer ? "顾客" : side === "right" ? "机器人" : "顾客";

        return (
          <div key={idx} className={`flex w-full ${side === "right" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[85%] px-3.5 py-2.5 rounded-2xl text-[13px] leading-relaxed shadow-sm ${
                side === "right"
                  ? "bg-primary text-primary-foreground rounded-br-md"
                  : "bg-card border border-border/60 text-foreground rounded-bl-md"
              }`}
            >
              <span
                className={`block text-[10px] font-semibold uppercase tracking-wide mb-1 ${
                  side === "right" ? "text-primary-foreground/60" : "text-muted-foreground/60"
                }`}
              >
                {senderLabel}
              </span>
              <span className="whitespace-pre-wrap">{cleanText}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
