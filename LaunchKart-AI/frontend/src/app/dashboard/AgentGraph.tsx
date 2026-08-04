"use client";

import { useNodesState, useEdgesState } from "@xyflow/react";
import { ReactFlow, MiniMap, Controls, Background } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AgentNode } from "./AgentNode";
import { Cpu, Sparkles } from "lucide-react";

const nodeTypes = {
  agent: AgentNode,
};

// Compact, high-readability 4-tier grid arrangement (No tiny zoomed-out nodes!)
const initialNodes = [
  // Tier 1: Core Strategy & Orchestration
  { id: "planner", type: "agent", position: { x: 260, y: 40 }, data: { id: "planner", label: "AI Launch Planner", description: "Architects the launch sequence & agent tasks" } },
  { id: "coordinator", type: "agent", position: { x: 640, y: 40 }, data: { id: "coordinator", label: "ROCm Hardware Coordinator", description: "Orchestrates multi-agent execution flow" } },

  // Tier 2: Intelligence & Research
  { id: "vision", type: "agent", position: { x: 50, y: 220 }, data: { id: "vision", label: "Visual Intelligence Engine", description: "Analyzes product imagery & visual features" } },
  { id: "product", type: "agent", position: { x: 350, y: 220 }, data: { id: "product", label: "Product Specs Extractor", description: "Extracts technical specs & USPs" } },
  { id: "research", type: "agent", position: { x: 650, y: 220 }, data: { id: "research", label: "Market Demand Analyzer", description: "Scrapes market trends & consumer demand" } },
  { id: "competitor", type: "agent", position: { x: 950, y: 220 }, data: { id: "competitor", label: "Competitor Intelligence Agent", description: "Benchmarks top 50 competing products" } },

  // Tier 3: Strategy & Content Generation
  { id: "pricing", type: "agent", position: { x: 50, y: 400 }, data: { id: "pricing", label: "Dynamic Pricing & Margin Agent", description: "Computes optimal margin & elasticity pricing" } },
  { id: "seo", type: "agent", position: { x: 350, y: 400 }, data: { id: "seo", label: "SEO & Keyword Generator", description: "Injects high-volume backend search keywords" } },
  { id: "branding", type: "agent", position: { x: 650, y: 400 }, data: { id: "branding", label: "Brand Storytelling Engine", description: "Crafts persuasive brand storytelling & copy" } },
  { id: "listing", type: "agent", position: { x: 950, y: 400 }, data: { id: "listing", label: "Multi-Channel Catalog Builder", description: "Generates Amazon A+ & Shopify listings" } },

  // Tier 4: Quality Assurance, Export & Memory
  { id: "marketing", type: "agent", position: { x: 50, y: 580 }, data: { id: "marketing", label: "Social & Ad Campaign Engine", description: "Creates viral social media ad campaigns" } },
  { id: "qa", type: "agent", position: { x: 350, y: 580 }, data: { id: "qa", label: "Compliance & Policy Guard", description: "Validates compliance, formatting & tone" } },
  { id: "marketplace", type: "agent", position: { x: 650, y: 580 }, data: { id: "marketplace", label: "Marketplace Syndication Engine", description: "Executes automated multi-channel exports" } },
  { id: "memory", type: "agent", position: { x: 950, y: 580 }, data: { id: "memory", label: "Semantic Vector Memory", description: "Persists vector embeddings into Chroma DB" } },

  // Tier 5: Analytics
  { id: "analytics", type: "agent", position: { x: 500, y: 750 }, data: { id: "analytics", label: "ROI & Conversion Analytics", description: "Computes projected revenue & conversion ROI" } },
];

const initialEdges = [
  { id: "e1", source: "planner", target: "coordinator", animated: true },
  { id: "e2", source: "coordinator", target: "vision", animated: true },
  { id: "e3", source: "coordinator", target: "product", animated: true },
  { id: "e4", source: "coordinator", target: "research", animated: true },
  { id: "e5", source: "coordinator", target: "competitor", animated: true },
  { id: "e6", source: "vision", target: "pricing", animated: true },
  { id: "e7", source: "product", target: "seo", animated: true },
  { id: "e8", source: "research", target: "branding", animated: true },
  { id: "e9", source: "competitor", target: "listing", animated: true },
  { id: "e10", source: "pricing", target: "marketing", animated: true },
  { id: "e11", source: "seo", target: "qa", animated: true },
  { id: "e12", source: "branding", target: "marketplace", animated: true },
  { id: "e13", source: "listing", target: "memory", animated: true },
  { id: "e14", source: "qa", target: "analytics", animated: true },
  { id: "e15", source: "marketplace", target: "analytics", animated: true },
];

export function AgentGraph() {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  return (
    <div className="h-[680px] w-full rounded-2xl overflow-hidden border border-white/15 bg-neutral-950/90 backdrop-blur-2xl shadow-[0_10px_40px_rgba(0,0,0,0.8)] relative group">
      {/* Top Floating Status Bar */}
      <div className="absolute top-4 left-4 z-10 flex items-center gap-3 bg-neutral-900/90 border border-white/15 px-4 py-2 rounded-xl backdrop-blur-md shadow-lg pointer-events-none">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-red-500 animate-pulse" />
          <span className="text-xs font-bold uppercase tracking-wider text-white">
            AMD Radeon ROCm Pipeline
          </span>
        </div>
        <span className="h-3 w-[1px] bg-white/20" />
        <div className="flex items-center gap-1.5 text-xs text-neutral-300 font-semibold">
          <Sparkles className="w-3.5 h-3.5 text-amber-400" />
          <span>15 Autonomous AI Agents</span>
        </div>
      </div>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        defaultEdgeOptions={{
          type: "smoothstep",
          animated: true,
          style: {
            stroke: "#ED1C24",
            strokeWidth: 2.5,
            filter: "drop-shadow(0 0 4px rgba(237,28,36,0.6))",
          },
        }}
        attributionPosition="bottom-left"
        minZoom={0.4}
        maxZoom={1.5}
      >
        <Background color="#262626" gap={20} size={1.5} />
        <Controls
          position="bottom-left"
          className="!bg-neutral-900/90 !border !border-white/15 !rounded-xl !shadow-xl !fill-white text-white overflow-hidden"
        />
        <MiniMap
          zoomable
          pannable
          position="top-right"
          style={{
            background: "#171717",
            border: "1px solid rgba(255,255,255,0.15)",
            borderRadius: "12px",
            height: 110,
            width: 170,
          }}
          nodeColor={(node) => {
            if (node.id === "planner" || node.id === "coordinator") return "#ED1C24";
            return "#3b82f6";
          }}
        />
      </ReactFlow>
    </div>
  );
}
