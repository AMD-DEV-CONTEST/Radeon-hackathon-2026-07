"use client";

import { useEffect, useState, useRef } from "react";
import { ChevronDown, ChevronUp, CheckCircle, Target, Database, Wrench, Sparkles, Activity, Layers } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { motion, AnimatePresence } from "framer-motion";
import { useLaunchStore } from "@/stores/launchStore";

export function AgentReasoningPanel() {
  const selectedAgentId = useLaunchStore((state) => state.selectedAgentId);
  const [expanded, setExpanded] = useState<string | null>("pricing");
  const panelRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    if (selectedAgentId) {
      setExpanded(selectedAgentId);
      setTimeout(() => {
        const el = panelRefs.current[selectedAgentId];
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      }, 100);
    }
  }, [selectedAgentId]);

  const allReasoning = [
    {
      id: "planner",
      agent: "AI Launch Planner",
      goal: "Architect the launch sequence and coordinate microservice execution pipelines.",
      reasoning: "Analyzed target sales channels (Amazon, Shopify, TikTok Shop) and product specification schemas. Formulated a 4-tier parallel execution DAG to maximize AMD GPU concurrency.",
      confidence: 99,
      tools: ["DAGScheduler", "DependencyResolver"],
      memory: "Loaded standard 14-service enterprise e-commerce syndication template.",
    },
    {
      id: "coordinator",
      agent: "ROCm Hardware Coordinator",
      goal: "Orchestrate inter-service memory passing and AMD Radeon GPU VRAM allocation.",
      reasoning: "Allocated 18.4GB of VRAM across 4 parallel worker threads on the AMD Radeon RX 7900 XTX. Verified zero deadlock risk and initiated subservice dispatch.",
      confidence: 98,
      tools: ["ROCmMemoryManager", "TaskDispatcher"],
      memory: "Historical VRAM operating ceiling maintained at 24.0 GB.",
    },
    {
      id: "vision",
      agent: "Visual Intelligence Engine",
      goal: "Analyze product imagery to extract visual aesthetics, color hex palettes, and material composition.",
      reasoning: "Executed computer vision inference on product photography using ROCm acceleration. Detected matte black anodized aluminum finish, RGB backlighting, and 75% compact layout.",
      confidence: 96,
      tools: ["ROCmVisionModel", "ColorPaletteExtractor"],
      memory: "Matched visual profile to 'High-End Peripheral Hardware' cluster.",
    },
    {
      id: "product",
      agent: "Product Specs Extractor",
      goal: "Extract technical specifications, key features, and target buyer personas.",
      reasoning: "Synthesized raw technical data into 5 core product feature attributes: Gasket-mount acoustics, hot-swappable PCB, tri-mode wireless, PBT double-shot keycaps, and 4000mAh battery.",
      confidence: 95,
      tools: ["SpecParser", "PersonaGenerator"],
      memory: "Target persona aligned with 'Enthusiast Typists & Hardware Professionals'.",
    },
    {
      id: "research",
      agent: "Market Demand Analyzer",
      goal: "Aggregate real-time market trends, keyword search volume, and consumer sentiment.",
      reasoning: "Indexed 1,200 recent community discussions and marketplace reviews. Identified growing consumer demand for factory-lubricated stabilizers and acoustic refinement.",
      confidence: 92,
      tools: ["TrendScraper", "SentimentAnalyzer"],
      memory: "Queried Chroma vector database for 'mechanical keyboard acoustics 2026'.",
    },
    {
      id: "competitor",
      agent: "Competitor Intelligence Agent",
      goal: "Benchmark against top 50 competing products across Amazon and Shopify sales channels.",
      reasoning: "Analyzed Keychron, NuPhy, and Akko product catalogs. Discovered average competitor MSRP is $145 with wired-only connectivity in this acoustic class.",
      confidence: 93,
      tools: ["AmazonScraper", "ShopifyTracker"],
      memory: "Retrieved competitor pricing embeddings from Chroma collection 'competitor_benchmarks'.",
    },
    {
      id: "pricing",
      agent: "Dynamic Pricing & Margin Agent",
      goal: "Determine optimal pricing strategy for gross margin maximization and market penetration.",
      reasoning: "Synthesized competitor price ceiling ($145) and vendor margin requirements (30%+). Formulated introductory retail price at $129.99 (35.4% profit margin) with an aggressive promotional voucher.",
      confidence: 97,
      tools: ["ElasticityModeler", "MarginCalculator"],
      memory: "Retrieved enterprise policy: 'Never undercut below 30% gross margin threshold'.",
    },
    {
      id: "seo",
      agent: "SEO & Keyword Generator",
      goal: "Optimize catalog titles and backend search discovery keywords for marketplace search algorithms.",
      reasoning: "Identified high-velocity search terms: 'gasket mount mechanical keyboard', 'hot swappable 75 percent', and 'creamy acoustic keyboard'. Engineered high-converting 195-character structured title.",
      confidence: 94,
      tools: ["KeywordPlanner", "SearchVolumeEstimator"],
      memory: "Retrieved top converting keyword clusters from vector collection 'seo_metadata'.",
    },
    {
      id: "branding",
      agent: "Brand Storytelling Engine",
      goal: "Craft compelling product attribute descriptions adhering to approved voice guidelines.",
      reasoning: "Adopted 'Premium Industrial Hardware' vocabulary. Generated 5 specification bullet points focusing on tactile precision, acoustic dampening, and ergonomic productivity.",
      confidence: 91,
      tools: ["CopywriterLLM", "ToneCheck"],
      memory: "Brand style guidelines loaded from collection 'vocabulary_rules'.",
    },
    {
      id: "listing",
      agent: "Multi-Channel Catalog Builder",
      goal: "Generate structured HTML/Markdown catalog feeds for Amazon A+ and Shopify.",
      reasoning: "Structured content into responsive HTML modules with comparison tables, technical spec grids, and feature highlight callout blocks.",
      confidence: 95,
      tools: ["HTMLBuilder", "MarkdownGenerator"],
      memory: "Schema matched to Shopify Storefront 2.0 & Amazon A+ Premium API standards.",
    },
    {
      id: "marketing",
      agent: "Social & Ad Campaign Engine",
      goal: "Generate promotional campaign copy for social commerce and search engine advertising.",
      reasoning: "Created 3 short-form video commerce hooks emphasizing acoustic typing feedback and 2 high-intent search engine ad variations.",
      confidence: 90,
      tools: ["AdCopyGenerator", "CommerceHookBuilder"],
      memory: "Loaded historical conversion rate vectors from collection 'campaign_metrics'.",
    },
    {
      id: "qa",
      agent: "Compliance & Policy Guard",
      goal: "Validate all generated catalog content for platform compliance, formatting schemas, and policy adherence.",
      reasoning: "Verified zero restricted promotional terms, checked character limits (<250 chars per attribute), and confirmed pricing arithmetic match across all data payloads.",
      confidence: 99,
      tools: ["ComplianceValidator", "SchemaCheck", "LinkVerifier"],
      memory: "Zero compliance infractions detected across all sales channels.",
    },
    {
      id: "marketplace",
      agent: "Marketplace Syndication Engine",
      goal: "Execute automated multi-channel API payload syndication and data export.",
      reasoning: "Generated verified JSON payloads for Amazon Selling Partner API (SP-API), Shopify GraphQL Admin API, and TikTok Shop Open API. Prepared batch upload bundles.",
      confidence: 98,
      tools: ["SPAPIExporter", "ShopifyGraphQLClient", "TikTokShopClient"],
      memory: "Syndication OAuth credentials verified for seller portal endpoints.",
    },
    {
      id: "memory",
      agent: "Semantic Vector Memory",
      goal: "Persist newly generated catalog embeddings into ChromaDB tiered storage.",
      reasoning: "Embedded 8 new knowledge vectors (pricing strategy, search discovery map, competitor benchmarks) into Chroma DB using ROCm local embeddings for ongoing pipeline refinement.",
      confidence: 99,
      tools: ["ChromaVectorStore", "ROCmEmbeddings"],
      memory: "Committed 8 vectors to namespace 'enterprise_catalog_memory'.",
    },
    {
      id: "analytics",
      agent: "ROI & Conversion Analytics",
      goal: "Compute projected revenue, gross merchandise value (GMV), and channel readiness score.",
      reasoning: "Calculated Channel Readiness Score at 96/100. Projected Month-1 sales volume at 1,450 units ($188,485 GMV) based on search discovery velocity and pricing elasticity models.",
      confidence: 94,
      tools: ["ROICalculator", "VelocityPredictor"],
      memory: "Historical benchmark model 'Q3_Hardware_Syndication_Model'.",
    },
  ];

  return (
    <div className="space-y-3 max-h-[680px] overflow-y-auto pr-1">
      {allReasoning.map((item) => {
        const isSelected = selectedAgentId === item.id;
        const isExpanded = expanded === item.id;

        return (
          <div
            key={item.id}
            ref={(el) => {
              panelRefs.current[item.id] = el;
            }}
            className={`border rounded-2xl overflow-hidden transition-all duration-300 shadow-lg backdrop-blur-xl ${
              isSelected
                ? "border-red-500 bg-gradient-to-r from-red-950/20 via-neutral-900 to-neutral-900 shadow-[0_0_30px_rgba(237,28,36,0.25)] ring-1 ring-red-500/50"
                : isExpanded
                ? "border-white/20 bg-neutral-900/90 shadow-xl"
                : "border-white/10 bg-neutral-900/40 hover:border-white/20 hover:bg-neutral-900/70"
            }`}
          >
            <button
              className="w-full flex items-center justify-between p-4 cursor-pointer text-left transition-colors"
              onClick={() => setExpanded(isExpanded ? null : item.id)}
            >
              <div className="flex items-center space-x-3.5">
                <div className={`w-9 h-9 rounded-xl border flex items-center justify-center transition-all ${
                  isSelected ? "bg-red-500/15 border-red-500/40 text-red-400" : "bg-white/5 border-white/10 text-neutral-300"
                }`}>
                  <Layers className="w-4 h-4" />
                </div>
                <div>
                  <span className="font-bold text-sm text-white tracking-tight flex items-center gap-2.5">
                    {item.agent}
                    {isSelected && (
                      <span className="px-2 py-0.5 rounded-full bg-red-500 text-[10px] font-bold uppercase tracking-wider text-white shadow-sm">
                        Active Selection
                      </span>
                    )}
                  </span>
                  <p className="text-xs text-neutral-400 font-normal line-clamp-1 mt-0.5">
                    {item.goal}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <Badge
                  variant={item.confidence >= 95 ? "success" : "default"}
                  className="font-semibold text-xs px-2.5 py-1 shadow-sm"
                >
                  {item.confidence}% Score
                </Badge>
                <div className="w-7 h-7 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-neutral-400 hover:text-white transition-colors">
                  {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </div>
              </div>
            </button>

            <AnimatePresence>
              {isExpanded && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.25, ease: "easeInOut" }}
                  className="overflow-hidden"
                >
                  <div className="p-5 pt-4 text-sm space-y-4 border-t border-white/10 bg-black/40">
                    {/* Goal Section */}
                    <div className="bg-white/5 p-4 rounded-xl border border-white/10 backdrop-blur-md">
                      <h5 className="flex items-center text-xs font-bold uppercase tracking-wider text-amber-400 mb-1.5">
                        <Target className="w-3.5 h-3.5 mr-1.5" /> Pipeline Objective
                      </h5>
                      <p className="text-neutral-200 text-xs leading-relaxed font-medium">
                        {item.goal}
                      </p>
                    </div>

                    {/* Reasoning Section */}
                    <div>
                      <h5 className="flex items-center text-xs font-bold uppercase tracking-wider text-emerald-400 mb-1.5">
                        <CheckCircle className="w-3.5 h-3.5 mr-1.5" /> AI Decision Logic & Inference Trace
                      </h5>
                      <p className="text-neutral-300 text-xs leading-relaxed bg-white/5 p-4 rounded-xl border border-white/10 backdrop-blur-md">
                        {item.reasoning}
                      </p>
                    </div>

                    {/* Footer Row: Tools & Memory */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 pt-1">
                      <div className="bg-white/5 p-3.5 rounded-xl border border-white/10 backdrop-blur-md">
                        <h5 className="flex items-center text-xs font-bold uppercase tracking-wider text-sky-400 mb-2">
                          <Wrench className="w-3.5 h-3.5 mr-1.5" /> Microservices Executed
                        </h5>
                        <div className="flex flex-wrap gap-1.5">
                          {item.tools.map((t) => (
                            <span
                              key={t}
                              className="px-2.5 py-1 rounded-lg bg-white/10 border border-white/15 text-[11px] font-medium text-neutral-200 shadow-sm"
                            >
                              {t}
                            </span>
                          ))}
                        </div>
                      </div>

                      <div className="bg-white/5 p-3.5 rounded-xl border border-white/10 backdrop-blur-md">
                        <h5 className="flex items-center text-xs font-bold uppercase tracking-wider text-purple-400 mb-1.5">
                          <Database className="w-3.5 h-3.5 mr-1.5" /> Chroma Vector Storage
                        </h5>
                        <p className="text-xs text-neutral-300 font-normal italic leading-relaxed">
                          &quot;{item.memory}&quot;
                        </p>
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}
    </div>
  );
}
