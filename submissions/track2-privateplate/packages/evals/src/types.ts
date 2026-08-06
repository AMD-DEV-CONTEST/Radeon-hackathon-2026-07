export type AgentScenario = {
  id: string;
  initialFixture: string;
  userTurns: string[];
  expectedTools: string[];
  forbiddenTools: string[];
  expectedFinalState: string;
  expectedConstraintIds?: string[];
  expectedPlanVersion?: number;
  expectedErrorCode?: string;
  assertions: string[];
};

export type ScenarioResult = {
  id: string;
  pass: boolean;
  failures: string[];
  phase: string;
  tools: string[];
  planVersion: number | null;
  durationMs: number;
  routingKinds?: string[];
  modelTraceCount?: number;
  modelStepCount?: number;
  taskOutcome?: {
    goal: string;
    status: string;
    verification: { passed: boolean };
    reasons: string[];
  };
};
