import { ArrowUp, Command, Sparkles, WandSparkles } from "lucide-react";
import type { FormEvent, KeyboardEvent } from "react";
import type { AgentMessage } from "../types";

interface AgentCommandProps {
  value: string;
  example: string;
  isProcessing: boolean;
  latestMessage?: AgentMessage;
  onChange: (value: string) => void;
  onSubmit: () => void;
}

export function AgentCommand({
  value,
  example,
  isProcessing,
  latestMessage,
  onChange,
  onSubmit,
}: AgentCommandProps) {
  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (
      event.key === "Enter" &&
      !event.nativeEvent.isComposing &&
      !value.trim() &&
      !isProcessing
    ) {
      event.preventDefault();
      onSubmit();
    }
  };

  return (
    <div className="agent-command-wrap">
      {latestMessage && (
        <div className="agent-response" role="status">
          <div className="agent-response-icon">
            <Sparkles size={12} />
          </div>
          <span>{latestMessage.response}</span>
          <time>{latestMessage.at}</time>
        </div>
      )}
      <form className="agent-command" onSubmit={handleSubmit}>
        <div className="agent-leading">
          {isProcessing ? (
            <span className="agent-thinking">
              <i />
              <i />
              <i />
            </span>
          ) : (
            <WandSparkles size={16} />
          )}
        </div>
        <input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={example}
          aria-label="给 ColorGraph Agent 的自然语言修改指令"
          title="输入后按回车发送；空输入直接按回车将运行灰色示例"
          disabled={isProcessing}
        />
        <div className="command-hint">
          <Command size={11} />
          K
        </div>
        <button
          className="command-submit"
          type="submit"
          aria-label="发送指令"
          disabled={!value.trim() || isProcessing}
        >
          <ArrowUp size={15} />
        </button>
      </form>
    </div>
  );
}
