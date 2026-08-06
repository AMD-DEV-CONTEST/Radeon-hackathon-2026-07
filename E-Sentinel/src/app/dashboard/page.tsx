"use client";

import { useState, useEffect } from "react";
import SidebarNav, { type DashboardTab } from "@/components/dashboard/SidebarNav";
import MobileNav from "@/components/dashboard/MobileNav";
import { Construction } from "lucide-react";
import OverviewPanel from "@/components/dashboard/OverviewPanel";
import QAPanel from "@/components/dashboard/QAPanel";
import BotConfigPanel from "@/components/dashboard/BotConfigPanel";
import ChatMonitorPanel from "@/components/dashboard/ChatMonitorPanel";
import KnowledgeBasePanel from "@/components/dashboard/KnowledgeBasePanel";
import CampaignSyncPanel from "@/components/dashboard/CampaignSyncPanel";
import InquiryLossPanel from "@/components/dashboard/InquiryLossPanel";
import DiagnosisPanel from "@/components/dashboard/DiagnosisPanel";
import SatisfactionPanel from "@/components/dashboard/SatisfactionPanel";
import ReportsPanel from "@/components/dashboard/ReportsPanel";
import AuditPanel from "@/components/dashboard/AuditPanel";
import CompliancePanel from "@/components/dashboard/CompliancePanel";
import IntentAccuracyPanel from "@/components/dashboard/IntentAccuracyPanel";
import WorkOrderPanel from "@/components/dashboard/WorkOrderPanel";
import EffectComparePanel from "@/components/dashboard/EffectComparePanel";
import PaymentReminderPanel from "@/components/dashboard/PaymentReminderPanel";
import AgentAssistPanel from "@/components/dashboard/AgentAssistPanel";
import AgentPerformancePanel from "@/components/dashboard/AgentPerformancePanel";
import LLMMetricsPanel from "@/components/dashboard/LLMMetricsPanel";
import PlatformManagementPanel from "@/components/dashboard/PlatformManagementPanel";
import ShadowApprovalPanel from "@/components/dashboard/ShadowApprovalPanel";
import QualityMonitorPanel from "@/components/dashboard/QualityMonitorPanel";
import ModelConfigPanel from "@/components/dashboard/ModelConfigPanel";
import PromptManagerPanel from "@/components/dashboard/PromptManagerPanel";
import CostSavingsPanel from "@/components/dashboard/CostSavingsPanel";
import UnresolvedPanel from "@/components/dashboard/UnresolvedPanel";
import ReleaseEvidencePanel from "@/components/dashboard/ReleaseEvidencePanel";
import { useDashboardAuth } from "@/components/dashboard/DashboardAuthGate";

const VALID_TABS = ["overview","qa","bot-config","chat-monitor","knowledge-base","campaign-sync","inquiry-loss","diagnosis","satisfaction","reports","audit","compliance","intent-accuracy","work-orders","effect-compare","payment-reminders","agent-assist","agent-performance","llm-metrics","platforms","shadow-approval","quality-monitor","model-configs","prompts","cost-savings","unresolved","release-evidence"];

export default function DashboardPage() {
  // Always start with "qa" on both server and client to avoid hydration mismatch
  const [dashboardTab, setDashboardTab] = useState<DashboardTab>(() => {
    if (typeof window === "undefined") return "qa";
    const tab = new URLSearchParams(window.location.search).get("tab");
    return tab && VALID_TABS.includes(tab) ? tab as DashboardTab : "qa";
  });
  const { role } = useDashboardAuth();

  // Sync tab changes to URL for shareable deep links
  useEffect(() => {
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("tab", dashboardTab);
      window.history.replaceState({}, "", url.toString());
    }
  }, [dashboardTab]);

  return (
    <>
      <SidebarNav activeTab={dashboardTab} onTabChange={setDashboardTab} role={role} />
      <MobileNav activeTab={dashboardTab} onTabChange={setDashboardTab} role={role} />
      <div className="flex-1 w-full pb-14 md:pb-0">
      <div key={dashboardTab} className="panel-animate h-full">
      {dashboardTab === "overview" ? (
        <OverviewPanel />
      ) : dashboardTab === "qa" ? (
        <QAPanel onNavigate={setDashboardTab} />
      ) : dashboardTab === "bot-config" ? (
        <BotConfigPanel />
      ) : dashboardTab === "chat-monitor" ? (
        <ChatMonitorPanel />
      ) : dashboardTab === "knowledge-base" ? (
        <KnowledgeBasePanel />
      ) : dashboardTab === "campaign-sync" ? (
        <CampaignSyncPanel />
      ) : dashboardTab === "inquiry-loss" ? (
        <InquiryLossPanel />
      ) : dashboardTab === "diagnosis" ? (
        <DiagnosisPanel />
      ) : dashboardTab === "satisfaction" ? (
        <SatisfactionPanel />
      ) : dashboardTab === "reports" ? (
        <ReportsPanel />
      ) : dashboardTab === "audit" ? (
        <AuditPanel />
      ) : dashboardTab === "compliance" ? (
        <CompliancePanel />
      ) : dashboardTab === "intent-accuracy" ? (
        <IntentAccuracyPanel />
      ) : dashboardTab === "work-orders" ? (
        <WorkOrderPanel />
      ) : dashboardTab === "effect-compare" ? (
        <EffectComparePanel />
      ) : dashboardTab === "payment-reminders" ? (
        <PaymentReminderPanel />
      ) : dashboardTab === "agent-assist" ? (
        <AgentAssistPanel />
      ) : dashboardTab === "agent-performance" ? (
        <AgentPerformancePanel onNavigate={setDashboardTab} />
      ) : dashboardTab === "llm-metrics" ? (
        <LLMMetricsPanel />
      ) : dashboardTab === "platforms" ? (
        <PlatformManagementPanel />
      ) : dashboardTab === "shadow-approval" ? (
        <ShadowApprovalPanel />
      ) : dashboardTab === "quality-monitor" ? (
        <QualityMonitorPanel />
      ) : dashboardTab === "model-configs" ? (
        <ModelConfigPanel />
      ) : dashboardTab === "prompts" ? (
        <PromptManagerPanel />
      ) : dashboardTab === "cost-savings" ? (
        <CostSavingsPanel />
      ) : dashboardTab === "unresolved" ? (
        <UnresolvedPanel />
      ) : dashboardTab === "release-evidence" ? (
        <ReleaseEvidencePanel />
      ) : (
        <div className="flex-1 flex items-center justify-center bg-background">
          <div className="text-center">
            <Construction className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" strokeWidth={1.5} />
            <h2 className="text-lg font-semibold text-foreground mb-1">功能面板</h2>
            <p className="text-sm text-muted-foreground">此功能面板建设中，请先使用「经营总览」Tab</p>
          </div>
        </div>
      )}
      </div>
      </div>

    </>
  );
}
