"use client";

import { agentsService } from "@/features/agents/services/agents.service";
import { useOrchestrationStore } from "@/features/agents/store/orchestration.store";
import type {
  LiveAgentRuntimeMap,
  OrchestrationContext,
  OrchestrationRequest,
  OrchestrationSnapshot,
} from "@/features/agents/types/orchestration.types";
import {
  getAgentFailedMessage,
  getOrchestrationErrorMessage,
  isRetryableOrchestrationError,
} from "@/features/agents/utils/orchestration-errors";
import { nextPendingStageId } from "@/features/agents/utils/orchestration-mappers";
import { candidateService } from "@/features/candidate/services/candidate.service";
import { interviewService } from "@/features/interview/services/interview.service";
import { reportService } from "@/features/report/services/report.service";

function assertNotCancelled(): void {
  if (useOrchestrationStore.getState().cancelled) {
    throw new Error("Workflow cancelled.");
  }
}

function toLiveMap(
  agents: ReadonlyArray<{
    id: string;
    status: string;
    currentTask: string;
  }>
): LiveAgentRuntimeMap {
  const map: LiveAgentRuntimeMap = {};

  for (const agent of agents) {
    if (
      agent.id === "resume" ||
      agent.id === "planner" ||
      agent.id === "technical" ||
      agent.id === "behavior" ||
      agent.id === "factChecker" ||
      agent.id === "evaluation" ||
      agent.id === "hiring"
    ) {
      map[agent.id] = {
        status:
          agent.status === "idle" ||
          agent.status === "running" ||
          agent.status === "busy" ||
          agent.status === "waiting" ||
          agent.status === "error" ||
          agent.status === "completed"
            ? agent.status
            : "waiting",
        currentTask: agent.currentTask,
      };
    }
  }

  return map;
}

async function runResumeUpload(context: OrchestrationContext): Promise<void> {
  const store = useOrchestrationStore.getState();
  store.beginStage("resumeUpload", "Validating uploaded resume");
  store.appendHistory({
    stageId: "resumeUpload",
    agentName: "System",
    action: "Validating resume upload",
    status: "running",
  });
  store.appendThought({
    agentId: "resumeUpload",
    agentName: "System",
    thought: `Resume ${context.resumeId} is ready for parsing.`,
  });

  assertNotCancelled();
  await candidateService.getResume(context.resumeId);

  store.completeStage("resumeUpload", "Resume available");
  store.appendHistory({
    stageId: "resumeUpload",
    agentName: "System",
    action: "Resume upload validated",
    status: "completed",
  });
}

async function runResumeParsingAndAgent(
  context: OrchestrationContext
): Promise<void> {
  const store = useOrchestrationStore.getState();

  store.beginStage("resumeParsing", "Parsing resume document");
  store.appendHistory({
    stageId: "resumeParsing",
    agentName: "Resume Agent",
    action: "Started resume parsing",
    status: "running",
  });
  store.appendThought({
    agentId: "resume",
    agentName: "Resume Agent",
    thought: "Extracting sections, skills, and experience timeline.",
  });

  assertNotCancelled();
  store.updateStage("resumeParsing", { progress: 45 });

  store.beginStage("resume", "Analyzing resume competencies");
  store.appendHistory({
    stageId: "resume",
    agentName: "Resume Agent",
    action: "POST /resume/analyze",
    status: "running",
  });

  try {
    const analysis = await candidateService.analyzeResume({
      resumeId: context.resumeId,
    });

    assertNotCancelled();

    store.completeStage("resumeParsing", "Resume parsed");
    store.completeStage("resume", "Resume analysis complete");
    store.patchFinalResult({ analysisId: analysis.analysisId });
    store.appendThought({
      agentId: "resume",
      agentName: "Resume Agent",
      thought:
        analysis.aiSummary ||
        "Resume signals extracted. Handing off to Planner Agent.",
    });
    store.appendHistory({
      stageId: "resume",
      agentName: "Resume Agent",
      action: "Resume analysis completed",
      status: "completed",
      detail: analysis.analysisId,
    });
  } catch (error) {
    const message = getAgentFailedMessage("Resume Agent", error);
    store.completeStage("resumeParsing", "Parsing interrupted");
    store.failStage("resume", message, isRetryableOrchestrationError(error));
    store.appendHistory({
      stageId: "resume",
      agentName: "Resume Agent",
      action: "Resume analysis failed",
      status: "failed",
      detail: message,
    });
    throw error;
  }
}

async function runPlannerAgent(
  context: OrchestrationContext
): Promise<OrchestrationContext> {
  const store = useOrchestrationStore.getState();
  store.beginStage("planner", "Planning interview strategy");
  store.appendHistory({
    stageId: "planner",
    agentName: "Planner Agent",
    action: "POST /interview/plan",
    status: "running",
  });
  store.appendThought({
    agentId: "planner",
    agentName: "Planner Agent",
    thought: "Designing question coverage, difficulty, and agent handoffs.",
  });

  try {
    assertNotCancelled();
    const [dossier, resume] = await Promise.all([
      candidateService.getCandidate(context.candidateId),
      candidateService.getResume(context.resumeId),
    ]);

    const planResponse = await interviewService.planInterview(
      {
        candidateId: context.candidateId,
        resumeId: context.resumeId,
        configuration: context.configuration,
      },
      { dossier, resume }
    );

    store.updateStage("planner", {
      progress: 60,
      currentTask: "Creating interview session",
    });
    store.appendHistory({
      stageId: "planner",
      agentName: "Planner Agent",
      action: "POST /interview/create",
      status: "running",
    });

    assertNotCancelled();
    const created = await interviewService.createInterview({
      candidateId: context.candidateId,
      resumeId: context.resumeId,
      configuration: context.configuration,
    });

    const nextContext: OrchestrationContext = {
      ...context,
      planId: planResponse.plan.id,
      interviewId: created.interviewId,
    };

    store.completeStage("planner", "Interview plan ready");
    store.patchFinalResult({
      planId: planResponse.plan.id,
      interviewId: created.interviewId,
    });
    store.hydrateContext(nextContext);
    store.appendThought({
      agentId: "planner",
      agentName: "Planner Agent",
      thought: `Plan ${planResponse.plan.id} created. Starting live agent orchestration.`,
    });
    store.appendHistory({
      stageId: "planner",
      agentName: "Planner Agent",
      action: "Interview session created",
      status: "completed",
      detail: created.interviewId,
    });

    return nextContext;
  } catch (error) {
    const message = getAgentFailedMessage("Planner Agent", error);
    store.failStage("planner", message, isRetryableOrchestrationError(error));
    store.appendHistory({
      stageId: "planner",
      agentName: "Planner Agent",
      action: "Planning failed",
      status: "failed",
      detail: message,
    });
    throw error;
  }
}

async function runLiveInterviewAgents(
  context: OrchestrationContext
): Promise<void> {
  const store = useOrchestrationStore.getState();
  if (!context.interviewId) {
    throw new Error("Interview id is required for live agent stages.");
  }

  store.beginStage("technical", "Starting technical interview agent");
  store.beginStage("behavior", "Arming behavioral agent");
  store.beginStage("factChecker", "Arming fact checker");
  store.appendHistory({
    stageId: "technical",
    agentName: "Technical Agent",
    action: "POST /interview/start",
    status: "running",
  });
  store.appendThought({
    agentId: "technical",
    agentName: "Technical Agent",
    thought: "Entering live interview loop with multi-agent handoffs.",
  });

  try {
    assertNotCancelled();
    await interviewService.startInterview({
      interviewId: context.interviewId,
    });

    store.updateStage("technical", {
      progress: 40,
      currentTask: "Technical probes in progress",
    });
    store.updateStage("behavior", {
      progress: 25,
      currentTask: "Listening for behavioral signals",
    });
    store.updateStage("factChecker", {
      progress: 20,
      currentTask: "Waiting for verifiable claims",
    });

    await orchestrationService.syncAgents();

    store.appendHistory({
      stageId: "technical",
      agentName: "Technical Agent",
      action: "Live interview started",
      status: "completed",
    });
  } catch (error) {
    const message = getAgentFailedMessage("Technical Agent", error);
    store.failStage("technical", message, isRetryableOrchestrationError(error));
    store.failStage("behavior", message, isRetryableOrchestrationError(error));
    store.failStage(
      "factChecker",
      message,
      isRetryableOrchestrationError(error)
    );
    store.appendHistory({
      stageId: "technical",
      agentName: "Technical Agent",
      action: "Failed to start interview",
      status: "failed",
      detail: message,
    });
    throw error;
  }
}

async function runEvaluationAndHiring(
  context: OrchestrationContext
): Promise<OrchestrationContext> {
  const store = useOrchestrationStore.getState();
  if (!context.interviewId) {
    throw new Error("Interview id is required to finalize orchestration.");
  }

  store.beginStage("evaluation", "Finalizing interview evaluation");
  store.appendHistory({
    stageId: "evaluation",
    agentName: "Evaluation Agent",
    action: "POST /interview/end",
    status: "running",
  });
  store.appendThought({
    agentId: "evaluation",
    agentName: "Evaluation Agent",
    thought: "Aggregating scores and closing the live interview session.",
  });

  try {
    assertNotCancelled();
    await interviewService.endInterview({
      interviewId: context.interviewId,
      reason: "completed",
    });

    store.completeStage("technical", "Technical stage complete");
    store.completeStage("behavior", "Behavioral stage complete");
    store.completeStage("factChecker", "Fact checking complete");
    store.completeStage("evaluation", "Evaluation complete");
  } catch (error) {
    const message = getAgentFailedMessage("Evaluation Agent", error);
    store.failStage(
      "evaluation",
      message,
      isRetryableOrchestrationError(error)
    );
    store.appendHistory({
      stageId: "evaluation",
      agentName: "Evaluation Agent",
      action: "Evaluation failed",
      status: "failed",
      detail: message,
    });
    throw error;
  }

  store.beginStage("hiring", "Generating hiring recommendation");
  store.beginStage("report", "Preparing interview report");
  store.appendHistory({
    stageId: "hiring",
    agentName: "Hiring Agent",
    action: "POST /report/generate",
    status: "running",
  });
  store.appendThought({
    agentId: "hiring",
    agentName: "Hiring Agent",
    thought: "Compiling recommendation and executive report package.",
  });

  try {
    assertNotCancelled();
    const generated = await reportService.generateReport({
      interviewId: context.interviewId,
    });

    let recommendation: string | null = null;
    if (generated.reportId) {
      try {
        const report = await reportService.getReport(generated.reportId);
        recommendation = report.recommendation;
      } catch {
        recommendation = null;
      }
    }

    const nextContext: OrchestrationContext = {
      ...context,
      reportId: generated.reportId,
    };

    store.completeStage("hiring", "Hiring recommendation ready");
    store.completeStage("report", "Interview report ready");
    store.patchFinalResult({
      reportId: generated.reportId,
      recommendation,
      completedAt: new Date().toISOString(),
    });
    store.hydrateContext(nextContext);
    store.appendHistory({
      stageId: "report",
      agentName: "Hiring Agent",
      action: "Report generated",
      status: "completed",
      detail: generated.reportId,
    });
    store.appendThought({
      agentId: "hiring",
      agentName: "Hiring Agent",
      thought: recommendation
        ? `Final recommendation: ${recommendation}.`
        : "Report generation queued successfully.",
    });

    return nextContext;
  } catch (error) {
    const message = getAgentFailedMessage("Hiring Agent", error);
    store.failStage("hiring", message, isRetryableOrchestrationError(error));
    store.failStage("report", message, isRetryableOrchestrationError(error));
    store.appendHistory({
      stageId: "hiring",
      agentName: "Hiring Agent",
      action: "Report generation failed",
      status: "failed",
      detail: message,
    });
    throw error;
  }
}

export const orchestrationService = {
  getSnapshot(): OrchestrationSnapshot {
    return useOrchestrationStore.getState().getSnapshot();
  },

  async syncAgents(): Promise<LiveAgentRuntimeMap> {
    const [overview, status] = await Promise.all([
      agentsService.getAgents().catch(() => null),
      agentsService.getAgentsStatus().catch(() => null),
    ]);

    const live = toLiveMap(status?.agents ?? overview?.agents ?? []);
    useOrchestrationStore.getState().syncLiveAgents(live);
    return live;
  },

  async startWorkflow(request: OrchestrationRequest): Promise<OrchestrationSnapshot> {
    const store = useOrchestrationStore.getState();
    store.reset();

    const context: OrchestrationContext = {
      candidateId: request.candidateId,
      resumeId: request.resumeId,
      configuration: request.configuration,
      analysisId: null,
      planId: null,
      interviewId: request.interviewId ?? null,
      reportId: null,
    };

    store.hydrateContext(context);
    store.setWorkflowStatus("running");
    store.appendHistory({
      stageId: "resumeUpload",
      agentName: "System",
      action: "Orchestration workflow started",
      status: "info",
    });

    try {
      await runResumeUpload(context);
      await runResumeParsingAndAgent(context);
      const planned = await runPlannerAgent(context);
      await runLiveInterviewAgents(planned);
      useOrchestrationStore.getState().setWorkflowStatus("running");
      return useOrchestrationStore.getState().getSnapshot();
    } catch (error) {
      const latest = useOrchestrationStore.getState();
      if (
        latest.cancelled ||
        getOrchestrationErrorMessage(error).includes("cancelled")
      ) {
        latest.markCancelled();
        return latest.getSnapshot();
      }

      latest.setLastError(getOrchestrationErrorMessage(error));
      latest.setWorkflowStatus(
        latest.stages.some((stage) => stage.status === "completed")
          ? "partial_success"
          : "failed"
      );
      throw error;
    }
  },

  async finalizeWorkflow(): Promise<OrchestrationSnapshot> {
    const store = useOrchestrationStore.getState();
    const context = store.context;
    if (!context?.interviewId) {
      throw new Error("No active interview available to finalize.");
    }

    store.setWorkflowStatus("running");

    try {
      await runEvaluationAndHiring(context);
      store.setWorkflowStatus("completed");
      return store.getSnapshot();
    } catch (error) {
      if (store.cancelled) {
        store.markCancelled();
        return store.getSnapshot();
      }

      store.setLastError(getOrchestrationErrorMessage(error));
      store.setWorkflowStatus("partial_success");
      throw error;
    }
  },

  async retryFailedStage(): Promise<OrchestrationSnapshot> {
    const store = useOrchestrationStore.getState();
    const context = store.context;
    if (!context) {
      throw new Error("No orchestration context available.");
    }

    const stageId = nextPendingStageId(store.stages);
    if (!stageId) {
      return store.getSnapshot();
    }

    store.setWorkflowStatus("running");
    store.updateStage(stageId, {
      status: "pending",
      error: null,
      progress: 0,
      currentTask: "Retrying...",
    });

    try {
      if (stageId === "resumeUpload") {
        await runResumeUpload(context);
      } else if (stageId === "resumeParsing" || stageId === "resume") {
        await runResumeParsingAndAgent(context);
      } else if (stageId === "planner") {
        await runPlannerAgent(context);
      } else if (
        stageId === "technical" ||
        stageId === "behavior" ||
        stageId === "factChecker"
      ) {
        await runLiveInterviewAgents(context);
      } else if (
        stageId === "evaluation" ||
        stageId === "hiring" ||
        stageId === "report"
      ) {
        await runEvaluationAndHiring(context);
        store.setWorkflowStatus("completed");
      }

      return store.getSnapshot();
    } catch (error) {
      store.setLastError(getOrchestrationErrorMessage(error));
      throw error;
    }
  },

  cancelWorkflow(): OrchestrationSnapshot {
    const store = useOrchestrationStore.getState();
    store.markCancelled();
    store.appendHistory({
      stageId: store.currentStageId ?? "resumeUpload",
      agentName: "System",
      action: "Workflow cancelled by user",
      status: "cancelled",
    });
    return store.getSnapshot();
  },
};
