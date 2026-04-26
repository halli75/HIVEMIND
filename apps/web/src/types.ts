export type AgentTier = "T1" | "T2" | "T3";

export type AgentStatus = "running" | "queued" | "fallback" | "winner";

export type SwarmAgent = {
  id: string;
  x: number;
  y: number;
  tier: AgentTier;
  status: AgentStatus;
  score: number;
  confidence: number;
  strategy: string;
};

export type SwarmMetrics = {
  axlMessages: number;
  zeroGInferenceCalls: number;
  aiqSize: number;
  fallbackCount: number;
  latestSwapReceipt: string;
};

export type LeaderboardEntry = {
  rank: number;
  agentId: string;
  strategy: string;
  tier: AgentTier;
  score: number;
  pnl: number;
  risk: number;
};
