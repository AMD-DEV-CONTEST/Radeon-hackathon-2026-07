import { useState } from "react";
import clsx from "clsx";

export interface ScopedArticle { id: string; type: string; content: string; scope?: string; }

export interface ScopeFilterProps { articles: ScopedArticle[]; }

const SCOPES = ["private", "partner", "public"] as const;
type Scope = typeof SCOPES[number];

export function ScopeFilter({ articles }: ScopeFilterProps) {
  const [active, setActive] = useState<Set<Scope>>(new Set(["private", "partner", "public"]));
  const toggle = (s: Scope) => {
    const n = new Set(active);
    n.has(s) ? n.delete(s) : n.add(s);
    setActive(n);
  };
  return (
    <div>
      <div className="flex gap-2 mb-4">
        {SCOPES.map((s, i) => (
          <button key={s} data-testid="scope-toggle"
            onClick={() => toggle(s)}
            className={clsx("px-3 py-1 rounded text-xs",
              active.has(s) ? "bg-indigo-600 text-white" : "bg-slate-800 text-slate-400")}>
            {s}
          </button>
        ))}
      </div>
      <ul className="space-y-1">
        {articles.map(a => {
          const ok = active.has((a.scope as Scope) ?? "public");
          return (
            <li key={a.id} className="text-sm">
              {ok ? a.content : <span className="text-slate-500 italic">out-of-scope</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
