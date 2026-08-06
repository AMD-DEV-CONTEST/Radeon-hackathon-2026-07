export interface AgentConfig {
  mode: string;
  orchestratorUrl: string;
  agentName: string;
  agentType: string;
  workspaceRoot: string;
  maxConcurrency: number;
  pollInterval: number;        // seconds
  maxTurnsPerTask: number;
  heartbeatInterval: number;  // seconds
  model: string;
  apiKey: string;
  apiBase: string;
  codexCommand: string;
  skill: string;      // path to SKILL.md, empty string = no skill loaded
  gatewayUrl: string; // Gateway WS base URL for standby mode, e.g. ws://host:8001
  gatewayToken: string; // Bearer token for gateway auth (empty = unauthenticated)
  gatewayUsername: string; // Auto-login: POST /auth/login to get token (optional)
  gatewayPassword: string; // Auto-login: paired with gatewayUsername
}
