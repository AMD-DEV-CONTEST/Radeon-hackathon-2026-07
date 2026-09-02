/**
 * PrismCodeBlock — 语法高亮代码块 + 一键复制
 * 
 * 依赖：prismjs（已安装）+ MessageContent.tsx 调用。
 * 支持常用语言自动检测 → 语言标签 + 复制按钮。
 */

import { useEffect, useRef, useState } from "react";
import Prism from "prismjs";
import { Copy, Check } from "lucide-react";
import "./prism-theme.css";

// 按需加载语言（缩小 bundle）
import "prismjs/components/prism-python";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-jsx";
import "prismjs/components/prism-tsx";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";
import "prismjs/components/prism-yaml";
import "prismjs/components/prism-rust";
import "prismjs/components/prism-go";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-css";
import "prismjs/components/prism-markdown";

const LANG_MAP: Record<string, string> = {
  py: "python", js: "javascript", ts: "typescript", jsx: "jsx", tsx: "tsx",
  sh: "bash", shell: "bash", zsh: "bash", rs: "rust", yml: "yaml",
  md: "markdown", ps1: "powershell", dockerfile: "docker",
};

interface PrismCodeBlockProps {
  language: string;
  code: string;
}

export default function PrismCodeBlock({ language, code }: PrismCodeBlockProps) {
  const ref = useRef<HTMLElement>(null);
  const [copied, setCopied] = useState(false);
  const langNorm = LANG_MAP[language] || language || "text";

  useEffect(() => {
    if (ref.current) {
      // 移除旧的高亮类名避免 Prism 重复处理
      ref.current.className = `language-${langNorm}`;
      Prism.highlightElement(ref.current);
    }
  }, [code, langNorm]);

  const doCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard denied */ }
  };

  return (
    <div
      className="group relative rounded-xl border my-2 overflow-hidden"
      style={{
        borderColor: "var(--color-border-subtle)",
        background: "var(--color-bg-input)",
      }}
    >
      {/* 顶栏：语言标签 + 复制按钮 */}
      <div
        className="flex items-center justify-between px-3 py-1.5 border-b"
        style={{ borderColor: "var(--color-border-subtle)" }}
      >
        <span
          className="text-[10px] font-medium uppercase tracking-wider"
          style={{ color: "var(--color-text-muted)" }}
        >
          {langNorm}
        </span>
        <button
          onClick={doCopy}
          className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium
                     opacity-0 group-hover:opacity-100 transition-opacity duration-150
                     hover:bg-white/[0.08]"
          style={{ color: "var(--color-text-muted)" }}
        >
          {copied ? (
            <>
              <Check size={11} className="text-emerald-400" />
              已复制
            </>
          ) : (
            <>
              <Copy size={11} />
              复制
            </>
          )}
        </button>
      </div>
      {/* 代码 */}
      <pre className="overflow-x-auto m-0 p-3" style={{ fontSize: "12.5px", lineHeight: "1.6" }}>
        <code ref={ref} className={`language-${langNorm}`}>
          {code}
        </code>
      </pre>
    </div>
  );
}
