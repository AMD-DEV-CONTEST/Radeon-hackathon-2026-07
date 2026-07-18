import clsx from "clsx";
import { HEADER_GRADIENT } from "./styles/theme";
import { StatusPill } from "./components/StatusPill";

export type ViewId = "overview" | "feed" | "detail" | "provenance" | "scope" | "bench" | "attack";

export interface LayoutProps {
  current: ViewId;
  onNavigate: (v: ViewId) => void;
  connected: boolean;
  children: React.ReactNode;
}

const TABS: { id: ViewId; label: string }[] = [
  { id: "overview", label: "Fabric Overview" },
  { id: "feed", label: "Article Feed" },
  { id: "provenance", label: "Provenance Graph" },
  { id: "scope", label: "Scope Filter" },
  { id: "bench", label: "Bench Panel" },
  { id: "attack", label: "Attack Matrix" },
];

export function Layout({ current, onNavigate, connected, children }: LayoutProps) {
  return (
    <div className="min-h-screen flex flex-col">
      <header className={clsx("flex items-center justify-between px-6 py-3", HEADER_GRADIENT)}>
        <h1 className="text-xl font-bold text-white">Perciqa Cortex</h1>
        <StatusPill connected={connected} />
      </header>
      <div className="flex flex-1">
        <nav className="w-56 p-4 bg-slate-900 border-r border-slate-800 flex flex-col gap-1">
          {TABS.map(t => (
            <button key={t.id}
              onClick={() => onNavigate(t.id)}
              className={clsx(
                "text-left px-3 py-2 rounded text-sm",
                current === t.id ? "bg-slate-700 text-white" : "text-slate-300 hover:bg-slate-800"
              )}>
              {t.label}
            </button>
          ))}
        </nav>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
