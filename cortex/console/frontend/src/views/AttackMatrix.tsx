import { useState } from "react";
import clsx from "clsx";
import { ATTACK_TECHNIQUES } from "../data/attackTechniques";

export interface AttackMatrixProps {
  counts: Record<string, number>;
  articlesFor: (id: string) => { id: string; content: string }[];
}

export function AttackMatrix({ counts, articlesFor }: AttackMatrixProps) {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <div>
      <div className="grid gap-1" style={{ gridTemplateColumns: "repeat(15, minmax(0, 1fr))" }}>
        {ATTACK_TECHNIQUES.map(tid => {
          const n = counts[tid] ?? 0;
          const color = n >= 3 ? "bg-red-500" : n >= 1 ? "bg-orange-500" : "bg-slate-800";
          return (
            <button key={tid} data-testid="attack-cell" data-attack-id={tid}
              onClick={() => setSelected(tid)}
              className={clsx("h-6 rounded text-[8px] text-slate-100", color)}>
              {tid.replace("T", "")}
            </button>
          );
        })}
      </div>
      <div className="mt-4">
        {selected && (
          <ul className="space-y-1 text-sm text-slate-200">
            {articlesFor(selected).map(a => <li key={a.id}>{a.content}</li>)}
          </ul>
        )}
      </div>
    </div>
  );
}
