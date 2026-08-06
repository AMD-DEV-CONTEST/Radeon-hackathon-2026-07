"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Bot } from "lucide-react";

interface Props {
  title: string;
  endpoint: string;
  body?: Record<string, unknown>;
  triggerLabel?: string;
  children?: React.ReactNode;
  /** 可选：自定义结果渲染函数。接收解析后的响应数据，返回 JSX。不传时降级为原始 JSON 文本。 */
  renderResult?: (data: unknown) => React.ReactNode;
  /** 未触发分析时的占位提示 */
  placeholder?: string;
}

export default function LlmAnalysisCard({
  title,
  endpoint,
  body,
  triggerLabel = "LLM 分析",
  children,
  renderResult,
  placeholder,
}: Props) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
      const result = await res.json();
      if (res.ok) {
        setData(result);
      } else {
        setError(result.error || "分析失败");
      }
    } catch {
      setError("网络错误");
    }
    setLoading(false);
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center justify-between">
          <span>{title}</span>
          <Button size="sm" variant="outline" onClick={run} disabled={loading}>
            {loading ? "分析中..." : triggerLabel}
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {children}
        {!loading && !data && !error && placeholder && (
          <div className="flex flex-col items-center justify-center py-8 border-2 border-dashed border-border rounded-lg mt-1">
            <Bot className="w-6 h-6 mb-2 text-muted-foreground/30" />
            <p className="text-xs text-muted-foreground/50 text-center">{placeholder}</p>
          </div>
        )}
        {data && renderResult ? (
          <div className="mt-3">{renderResult(data)}</div>
        ) : data ? (
          <pre className="mt-3 text-xs bg-muted/50 rounded-md p-3 max-h-[300px] overflow-y-auto whitespace-pre-wrap">
            {typeof data === "string" ? data : JSON.stringify(data, null, 2)}
          </pre>
        ) : null}
        {error && (
          <p className="mt-2 text-sm text-red-600">错误: {error}</p>
        )}
      </CardContent>
    </Card>
  );
}
