// Agent 工作区（节点⑤真实数据接线）
// 数据源：/api/agents → { agents:[{name,role,backend,id}] }

import { useEffect, useState } from "react";
import { Brain, Wrench, ClipboardCheck, Users, Loader2, AlertCircle } from "lucide-react";
import { fetchAgents, type AgentInfo } from "./lib/api";

const ROLE_META: Record<string, { icon: JSX.Element; label: string; abilities: string; desc: string; color: string }> = {
  researcher: {
    icon: <Brain size={22} />, label: "思考与分析", color: "emerald",
    abilities: "研究 · 规划 · 推理 · 决策 · 需求分析",
    desc: "通用推理引擎，负责任务理解、信息检索和战略规划",
  },
  engineer: {
    icon: <Wrench size={22} />, label: "工程与执行", color: "amber",
    abilities: "编码 · 文件操作 · 测试 · 部署 · 重构",
    desc: "代码工程引擎，负责软件开发、文件修改和工程执行",
  },
  pm: {
    icon: <ClipboardCheck size={22} />, label: "协调与调度", color: "purple",
    abilities: "任务拆解 · 分配 · 进度跟踪 · 结果整合",
    desc: "协调者，负责任务编排、Agent 调度与结果汇总",
  },
};

export default function AgentWorkspace() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchAgents().then(setAgents).catch((e) => setError(e?.message || "加载失败")).finally(() => setLoading(false));
  }, []);

  return (
    <main className="flex-1 overflow-auto p-6 bg-zinc-50 dark:bg-zinc-950">
      <h2 className="text-lg font-semibold mb-1 flex items-center gap-2"><Users size={18} /> Agent 工作区</h2>
      <p className="text-xs text-zinc-400 mb-6">AI 数字员工团队 · 数据来自后端 /api/agents 实时注册表</p>

      {loading && <div className="flex items-center gap-2 text-zinc-400 text-xs py-8 justify-center"><Loader2 size={14} className="animate-spin" /> 加载 Agent 列表…</div>}
      {error && <div className="flex items-center gap-2 text-red-500 text-xs"><AlertCircle size={14} /> {error}</div>}

      <div className="grid grid-cols-1 gap-4">
        {agents.map((a) => {
          const meta = ROLE_META[a.role] || { icon: <Users size={22} />, label: a.role, abilities: "-", desc: "-", color: "zinc" };
          return (
            <div key={a.id} className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden">
              <div className="flex">
                <div className="w-48 p-5 border-r border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900">
                  <div className="flex items-center gap-3 mb-3">
                    <span className={`text-${meta.color}-500`}>{meta.icon}</span>
                    <div>
                      <div className="font-semibold text-sm">{a.name}</div>
                      <div className="text-[10px] text-zinc-400">{meta.label}</div>
                    </div>
                  </div>
                  <div className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] bg-${meta.color}-100 text-${meta.color}-700 dark:bg-${meta.color}-900/30 dark:text-${meta.color}-300`}>
                    <span className="w-1.5 h-1.5 rounded-full bg-current" />在线
                  </div>
                </div>
                <div className="flex-1 p-5">
                  <div className="grid grid-cols-2 gap-4 text-xs">
                    <div>
                      <div className="text-zinc-400 mb-1">能力</div>
                      <div className="text-zinc-600 dark:text-zinc-300">{meta.abilities}</div>
                    </div>
                    <div>
                      <div className="text-zinc-400 mb-1">后端 / ID</div>
                      <div className="text-zinc-600 dark:text-zinc-300 font-mono">{a.backend} · {a.id}</div>
                    </div>
                  </div>
                  <div className="mt-3 text-xs text-zinc-400">{meta.desc}</div>
                </div>
              </div>
            </div>
          );
        })}
        {!loading && !error && agents.length === 0 && (
          <div className="text-center text-xs text-zinc-400 py-8">后端未注册任何 Agent</div>
        )}
      </div>
    </main>
  );
}
