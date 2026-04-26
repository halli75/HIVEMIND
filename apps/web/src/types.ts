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

export type ScenarioRequest = {
  scenario_id: string;
  label: string;
  volatility: number;
  liquidity_delta: number;
  sentiment: number;
  gas_pressure: number;
  signal_strength: number;
};

export type ConnectionMode = "api" | "mock";

export type ConnectionBadge = {
  label: string;
  tone: "live" | "mock" | "offline" | "pending";
};

export type RunTranscript = {
  latestScenario: string;
  axlMessageCount: number;
  zeroGStorageUri: string;
  zeroGStorageHash: string;
  inftToken: string;
  inftAddress: string;
  uniswapQuote: string;
  uniswapSwapReceipt: string;
};

export type SwarmStreamState = {
  agents: SwarmAgent[];
  metrics: SwarmMetrics;
  leaderboard: LeaderboardEntry[];
  tick: number;
  mode: ConnectionMode;
  badges: ConnectionBadge[];
  transcript: RunTranscript;
  isRunningScenario: boolean;
  error: string | null;
  runScenario: (scenarioText: string) => Promise<void>;
};
