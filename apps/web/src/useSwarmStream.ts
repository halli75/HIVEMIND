import { useCallback, useEffect, useMemo, useState } from "react";
import type {
  AgentStatus,
  AgentTier,
  Archetype,
  AxlEdgeMessage,
  ConnectionBadge,
  InferenceBudget,
  LeaderboardEntry,
  RunTranscript,
  ScenarioRequest,
  SwarmAgent,
  SwarmMetrics,
  SwarmStreamState,
} from "./types";
import { useMockSwarm } from "./useMockSwarm";

const KNOWN_ARCHETYPES: Archetype[] = [
  "whale",
  "degen",
  "lp_provider",
  "arbitrageur",
  "governance_voter",
  "stablecoin_arb",
  "mev_searcher",
];

const archetypeFromApi = (value: string): Archetype =>
  (KNOWN_ARCHETYPES as string[]).includes(value) ? (value as Archetype) : "degen";

type ApiAgent = {
  agent_id: string;
  archetype: string;
  tier: number;
  action: string;
  confidence: number;
  pnl_bps: number;
  aiq: number;
  score: number;
  rationale?: string;
};

type ApiTierMetric = {
  tier: number;
  agent_count: number;
  inference_calls: number;
  fallback_count: number;
  aiq_size: number;
};

type ApiLeaderboardEntry = {
  rank: number;
  agent_id: string;
  archetype: string;
  tier: number;
  action: string;
  score: number;
  confidence: number;
  pnl_bps: number;
  aiq: number;
};

type ApiScenario = {
  scenario_id: string;
  label: string;
  volatility: number;
  liquidity_delta: number;
  sentiment: number;
  gas_pressure: number;
  signal_strength: number;
};

type ApiIntegrations = {
  zero_g_compute?: Record<string, unknown>;
  zero_g_storage?: Record<string, unknown>;
  gensyn_axl?: Record<string, unknown>;
  uniswap?: Record<string, unknown>;
};

type ApiSnapshot = {
  sequence: number;
  run_mode?: string;
  scenario: ApiScenario;
  agents: ApiAgent[];
  tier_metrics: ApiTierMetric[];
  leaderboard: ApiLeaderboardEntry[];
  integrations: ApiIntegrations;
  transcript?: Record<string, unknown>;
  proof?: Record<string, unknown>;
};

type SnapshotEvent = {
  type: string;
  snapshot?: ApiSnapshot;
  message?: string;
};

const API_URL = (import.meta.env.VITE_HIVEMIND_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const FALLBACK_ERROR = "API unavailable; using deterministic mock stream.";

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const stringValue = (source: Record<string, unknown> | undefined, keys: string[], fallback = "pending") => {
  for (const key of keys) {
    const value = source?.[key];
    if (typeof value === "string" && value.length > 0) return value;
    if (typeof value === "number") return String(value);
  }
  return fallback;
};

const numberValue = (source: Record<string, unknown> | undefined, keys: string[], fallback = 0) => {
  for (const key of keys) {
    const value = source?.[key];
    if (typeof value === "number") return value;
  }
  return fallback;
};

const nullableNumberValue = (source: Record<string, unknown> | undefined, keys: string[]) => {
  for (const key of keys) {
    const value = source?.[key];
    if (typeof value === "number") return value;
  }
  return null;
};

const stringArrayValue = (source: Record<string, unknown> | undefined, key: string) => {
  const value = source?.[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
};

const objectValue = (source: Record<string, unknown> | undefined, key: string) => {
  const value = source?.[key];
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
};

const receiptLabel = (receipt: Record<string, unknown> | undefined) => {
  const hash = stringValue(receipt, ["transaction_hash", "tx_hash", "hash"], "");
  const status = stringValue(receipt, ["status"], "pending");
  return hash || status;
};

const latencyLabel = (value: number | null) => (value === null ? "pending" : `${value.toFixed(1)} ms`);

const tierFromApi = (tier: number): AgentTier => {
  if (tier === 1) return "T1";
  if (tier === 2) return "T2";
  return "T3";
};

const statusFromApi = (agent: ApiAgent, index: number, winnerId: string | undefined): AgentStatus => {
  if (agent.agent_id === winnerId) return "winner";
  if (agent.confidence < 0.5) return "fallback";
  if (index % 19 === 0) return "queued";
  return "running";
};

const positionForAgent = (agentId: string, index: number, sequence: number, total: number) => {
  const ring = Math.sqrt((index + 1) / Math.max(1, total));
  const seed = [...agentId].reduce((sum, char) => sum + char.charCodeAt(0), 0);
  const angle = index * 2.399963 + seed * 0.001 + sequence * 0.025;

  return {
    x: clamp(50 + Math.cos(angle) * ring * 46, 3, 97),
    y: clamp(50 + Math.sin(angle) * ring * 42, 3, 97),
  };
};

const expandVisualAgents = (
  apiAgents: ApiAgent[],
  targetCount: number,
  sequence: number,
  winnerId: string | undefined,
): SwarmAgent[] => {
  if (apiAgents.length === 0) return [];

  return Array.from({ length: Math.max(targetCount, apiAgents.length) }, (_, index) => {
    const source = apiAgents[index % apiAgents.length];
    const generation = Math.floor(index / apiAgents.length);
    const visualId = generation === 0 ? source.agent_id : `${source.agent_id}-v${generation + 1}`;
    const position = positionForAgent(visualId, index, sequence, Math.max(targetCount, apiAgents.length));
    const isCanonicalWinner = source.agent_id === winnerId && generation === 0;
    const scorePulse = Math.sin((sequence + index) / 5) * 0.35 - generation * 0.04;

    return {
      id: visualId,
      x: position.x,
      y: position.y,
      tier: tierFromApi(source.tier),
      status: isCanonicalWinner ? "winner" : statusFromApi(source, index, undefined),
      score: clamp(source.score + scorePulse, 0, 100),
      confidence: source.confidence,
      strategy: `${source.archetype} / ${source.action}`,
      archetype: archetypeFromApi(source.archetype),
      sourceId: source.agent_id,
      action: source.action,
      pnl_bps: source.pnl_bps,
      aiq: source.aiq,
      rationale: source.rationale,
    };
  });
};

const extractAxlMessages = (
  gensynAxl: Record<string, unknown> | undefined,
  sequence: number,
): AxlEdgeMessage[] => {
  const transcript = gensynAxl?.["transcript"];
  if (!Array.isArray(transcript)) return [];
  return transcript
    .filter((entry): entry is Record<string, unknown> => !!entry && typeof entry === "object")
    .map((entry, index) => {
      const id = typeof entry["id"] === "string" ? (entry["id"] as string) : `axl-${sequence}-${index}`;
      const source = typeof entry["source_node"] === "string" ? (entry["source_node"] as string) : "";
      const target = typeof entry["target"] === "string" ? (entry["target"] as string) : "";
      const messageType = typeof entry["type"] === "string" ? (entry["type"] as string) : "MESSAGE";
      return { id, source, target, type: messageType, tick: sequence };
    })
    .filter((message) => message.source.length > 0 && message.target.length > 0);
};

const scenarioFromText = (scenarioText: string): ScenarioRequest => {
  const normalized = scenarioText.trim() || "Operator injected scenario";
  const lower = normalized.toLowerCase();
  const words = lower.split(/\s+/).filter(Boolean);
  const hash = [...normalized].reduce((sum, char) => (sum * 31 + char.charCodeAt(0)) % 100000, 17);

  const volatilityHint =
    (lower.match(/volatil|spike|shock|crash|surge|breakout/g)?.length ?? 0) * 0.18 + normalized.length / 420;
  const liquidityDelta =
    lower.includes("thin") || lower.includes("crunch") || lower.includes("drain")
      ? -0.45
      : lower.includes("deep") || lower.includes("improve")
        ? 0.32
        : ((hash % 61) - 30) / 100;
  const sentiment =
    lower.includes("bear") || lower.includes("sell") || lower.includes("risk")
      ? -0.5
      : lower.includes("bull") || lower.includes("buy") || lower.includes("rally")
        ? 0.45
        : (((hash / 7) % 101) - 50) / 100;
  const gasPressure =
    lower.includes("gas") || lower.includes("congestion") ? 0.72 : 0.16 + ((hash % 35) / 100);

  return {
    scenario_id: `web-${Date.now().toString(36)}`,
    label: words.slice(0, 8).join(" ") || "Operator scenario",
    volatility: clamp(volatilityHint, 0.05, 0.95),
    liquidity_delta: clamp(liquidityDelta, -0.95, 0.95),
    sentiment: clamp(sentiment, -0.95, 0.95),
    gas_pressure: clamp(gasPressure, 0.05, 0.95),
    signal_strength: clamp(0.45 + words.length / 80, 0.35, 0.9),
  };
};

const toWebSocketUrl = (apiUrl: string) => {
  const url = new URL(apiUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `${url.pathname.replace(/\/$/, "")}/ws/state`;
  return url.toString();
};

function mapSnapshot(snapshot: ApiSnapshot, visualAgentCount: number) {
  const winnerId = snapshot.leaderboard[0]?.agent_id;
  const agents = expandVisualAgents(snapshot.agents, visualAgentCount, snapshot.sequence, winnerId);

  const tierMetrics = snapshot.tier_metrics;
  const integrations = snapshot.integrations;
  const zeroGCompute = integrations.zero_g_compute;
  const zeroGStorage = integrations.zero_g_storage;
  const gensynAxl = integrations.gensyn_axl;
  const uniswap = integrations.uniswap;
  const proof = snapshot.proof;
  const proofStorage = objectValue(proof, "zero_g_storage");
  const proofAxl = objectValue(proof, "axl");
  const proofInft = objectValue(proof, "inft");
  const proofUniswap = objectValue(proof, "uniswap");
  const proofReceipt = objectValue(proofUniswap, "swap_receipt");
  const integrationReceipt = objectValue(uniswap, "swap_receipt");
  const fallbackCount = tierMetrics.reduce((sum, tier) => sum + tier.fallback_count, 0);
  const axlFailedNodes = stringArrayValue(gensynAxl, "failed_nodes");
  const axlP50LatencyMs = nullableNumberValue(gensynAxl, ["p50_latency_ms"]);
  const axlP95LatencyMs = nullableNumberValue(gensynAxl, ["p95_latency_ms"]);

  const metrics: SwarmMetrics = {
    axlMessages: numberValue(gensynAxl, ["messages", "message_count"], agents.length),
    axlNodesOnline: numberValue(gensynAxl, ["nodes_online"], 1),
    axlFailedNodes: axlFailedNodes.length,
    axlLastMessageType: stringValue(gensynAxl, ["last_message_type"], "pending"),
    axlP50LatencyMs,
    axlP95LatencyMs,
    zeroGInferenceCalls: numberValue(
      zeroGCompute,
      ["inference_calls", "calls"],
      tierMetrics.reduce((sum, tier) => sum + tier.inference_calls, 0),
    ),
    aiqSize: Math.round(tierMetrics.reduce((sum, tier) => sum + tier.aiq_size, 0) * 100),
    fallbackCount,
    latestSwapReceipt: receiptLabel(proofReceipt ?? integrationReceipt),
  };

  const leaderboard: LeaderboardEntry[] = snapshot.leaderboard.slice(0, 8).map((entry) => ({
    rank: entry.rank,
    agentId: entry.agent_id,
    strategy: `${entry.archetype} / ${entry.action}`,
    tier: tierFromApi(entry.tier),
    score: entry.score,
    pnl: entry.pnl_bps / 100,
    risk: Math.max(0.1, 10 - entry.confidence * 9),
  }));

  const transcript: RunTranscript = {
    latestScenario: `${snapshot.scenario.label} (${snapshot.scenario.scenario_id})`,
    axlMessageCount: metrics.axlMessages,
    axlNodesOnline: metrics.axlNodesOnline,
    axlLastMessageType: stringValue(proofAxl, ["last_message_type"], metrics.axlLastMessageType),
    axlP50LatencyMs: latencyLabel(nullableNumberValue(proofAxl, ["p50_latency_ms"]) ?? metrics.axlP50LatencyMs),
    axlP95LatencyMs: latencyLabel(nullableNumberValue(proofAxl, ["p95_latency_ms"]) ?? metrics.axlP95LatencyMs),
    axlTranscriptPath: stringValue(proofAxl, ["transcript_path"], stringValue(gensynAxl, ["transcript_path"])),
    zeroGStorageUri: stringValue(proofStorage, ["uri", "storage_uri"], stringValue(zeroGStorage, ["uri", "storage_uri"])),
    zeroGStorageHash: stringValue(
      proofStorage,
      ["storage_hash", "hash", "state_digest"],
      stringValue(zeroGStorage, ["storage_hash", "hash", "state_digest"]),
    ),
    inftStatus: stringValue(proofInft, ["status"], "placeholder"),
    inftToken: stringValue(proofInft, ["token_id", "tokenId"], "pending mint"),
    inftAddress: stringValue(proofInft, ["address", "contract_address", "local_address"], "pending local address"),
    uniswapQuote: stringValue(uniswap, ["quote_id", "quoteId"]),
    uniswapSwapReceipt: metrics.latestSwapReceipt,
  };

  const axlMessages = extractAxlMessages(gensynAxl, snapshot.sequence);

  const inferenceCallsThisTick = tierMetrics.reduce((sum, tier) => sum + tier.inference_calls, 0);
  const aiqOccupied = tierMetrics.reduce(
    (sum, tier) => sum + (tier.aiq_size > 0 ? Math.min(10, Math.round(tier.aiq_size * 10)) : 0),
    0,
  );
  const inferenceBudget: InferenceBudget = {
    callsThisTick: inferenceCallsThisTick,
    cap: 10,
    callsPerTickAvg: snapshot.sequence > 0 ? metrics.zeroGInferenceCalls / Math.max(1, snapshot.sequence) : 0,
    aiqSlotsActive: Math.min(10, aiqOccupied),
    aiqSlotsTotal: 10,
  };

  return {
    agents,
    metrics,
    leaderboard,
    transcript,
    tick: snapshot.sequence,
    integrations,
    axlMessages,
    totalAgentCount: snapshot.agents.length,
    inferenceBudget,
  };
}

const mockTranscript = (scenario: string, metrics: SwarmMetrics): RunTranscript => ({
  latestScenario: scenario,
  axlMessageCount: metrics.axlMessages,
  axlNodesOnline: metrics.axlNodesOnline,
  axlLastMessageType: metrics.axlLastMessageType,
  axlP50LatencyMs: latencyLabel(metrics.axlP50LatencyMs),
  axlP95LatencyMs: latencyLabel(metrics.axlP95LatencyMs),
  axlTranscriptPath: "mock://axl/offline",
  zeroGStorageUri: "mock://0g-storage/offline/swarm-state",
  zeroGStorageHash: "mock-local",
  inftStatus: "placeholder",
  inftToken: "pending mint",
  inftAddress: "pending local address",
  uniswapQuote: "pending quote",
  uniswapSwapReceipt: metrics.latestSwapReceipt,
});

const badgesFor = (mode: "api" | "mock", integrations?: ApiIntegrations): ConnectionBadge[] => {
  if (mode === "mock") {
    return [
      { label: "Mock fallback", tone: "mock" },
      { label: "AXL mock", tone: "mock" },
      { label: "0G mock", tone: "mock" },
      { label: "Uniswap mock", tone: "mock" },
    ];
  }

  const axlMode = stringValue(integrations?.gensyn_axl, ["mode"], "mock");
  const zeroGComputeMode = stringValue(integrations?.zero_g_compute, ["mode"], "mock");
  const zeroGStorageMode = stringValue(integrations?.zero_g_storage, ["mode"], "mock");
  const uniswapMode = stringValue(integrations?.uniswap, ["mode"], "");
  const combinedMode = (...modes: string[]) => {
    if (modes.some((sourceMode) => sourceMode.startsWith("live"))) return "live";
    if (modes.includes("seed_replay")) return "seed_replay";
    return modes.find(Boolean) ?? "mock";
  };
  const labelFor = (name: string, sourceMode: string) => {
    if (sourceMode === "local_axl") return `${name} live`;
    if (sourceMode.startsWith("live")) return `${name} live`;
    if (sourceMode === "unavailable") return `${name} unavailable`;
    if (sourceMode === "seed_replay") return `${name} replay`;
    return `${name} mock`;
  };
  const toneFor = (sourceMode: string): ConnectionBadge["tone"] => {
    if (sourceMode === "unavailable") return "offline";
    return sourceMode.startsWith("live") || sourceMode === "local_axl" ? "live" : "mock";
  };

  return [
    { label: "API connected", tone: "live" },
    { label: labelFor("AXL", axlMode), tone: toneFor(axlMode) },
    {
      label: labelFor("0G", combinedMode(zeroGComputeMode, zeroGStorageMode)),
      tone: toneFor(combinedMode(zeroGComputeMode, zeroGStorageMode)),
    },
    {
      label: labelFor("Uniswap", uniswapMode),
      tone: toneFor(uniswapMode),
    },
  ];
};

export function useSwarmStream(agentCount: number, scenario: string): SwarmStreamState {
  const mock = useMockSwarm(agentCount, scenario);
  const [snapshot, setSnapshot] = useState<ApiSnapshot | null>(null);
  const [isApiOnline, setIsApiOnline] = useState(false);
  const [error, setError] = useState<string | null>(API_URL ? null : "VITE_HIVEMIND_API_URL is not configured.");
  const [isRunningScenario, setIsRunningScenario] = useState(false);

  useEffect(() => {
    if (!API_URL) return;

    const controller = new AbortController();
    fetch(`${API_URL}/state`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`GET /state returned ${response.status}`);
        return response.json() as Promise<ApiSnapshot>;
      })
      .then((nextSnapshot) => {
        setSnapshot(nextSnapshot);
        setIsApiOnline(true);
        setError(null);
      })
      .catch((fetchError: unknown) => {
        if (controller.signal.aborted) return;
        setIsApiOnline(false);
        setError(fetchError instanceof Error ? fetchError.message : FALLBACK_ERROR);
      });

    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!API_URL) return;

    let socket: WebSocket | null = null;
    let didClose = false;

    try {
      socket = new WebSocket(toWebSocketUrl(API_URL));
    } catch (wsError) {
      setIsApiOnline(false);
      setError(wsError instanceof Error ? wsError.message : FALLBACK_ERROR);
      return;
    }

    socket.onopen = () => {
      setIsApiOnline(true);
      setError(null);
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data as string) as SnapshotEvent;
        if (payload.type === "snapshot" && payload.snapshot) {
          setSnapshot(payload.snapshot);
          setIsApiOnline(true);
          setError(null);
        } else if (payload.type === "error") {
          setError(payload.message ?? "WebSocket event rejected.");
        }
      } catch {
        setError("WebSocket emitted an unreadable state event.");
      }
    };

    socket.onerror = () => {
      setIsApiOnline(false);
      setError(FALLBACK_ERROR);
    };

    socket.onclose = () => {
      if (!didClose) {
        setIsApiOnline(false);
        setError(FALLBACK_ERROR);
      }
    };

    return () => {
      didClose = true;
      socket?.close();
    };
  }, []);

  const mappedSnapshot = useMemo(() => (snapshot ? mapSnapshot(snapshot, agentCount) : null), [agentCount, snapshot]);
  const mode = API_URL && isApiOnline && mappedSnapshot ? "api" : "mock";

  const runScenario = useCallback(async (scenarioText: string) => {
    if (!API_URL) {
      setError("VITE_HIVEMIND_API_URL is not configured; scenario is driving mock fallback only.");
      return;
    }

    setIsRunningScenario(true);
    try {
      const response = await fetch(`${API_URL}/scenario`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(scenarioFromText(scenarioText)),
      });

      if (!response.ok) throw new Error(`POST /scenario returned ${response.status}`);

      const event = (await response.json()) as SnapshotEvent;
      if (event.type === "snapshot" && event.snapshot) {
        setSnapshot(event.snapshot);
        setIsApiOnline(true);
        setError(null);
      }
    } catch (runError) {
      setIsApiOnline(false);
      setError(runError instanceof Error ? runError.message : FALLBACK_ERROR);
    } finally {
      setIsRunningScenario(false);
    }
  }, []);

  if (mode === "api" && mappedSnapshot) {
    return {
      ...mappedSnapshot,
      mode,
      badges: badgesFor(mode, mappedSnapshot.integrations),
      isRunningScenario,
      error,
      runScenario,
    };
  }

  return {
    ...mock,
    mode,
    badges: badgesFor("mock"),
    transcript: mockTranscript(scenario, mock.metrics),
    totalAgentCount: mock.agents.length,
    isRunningScenario,
    error,
    runScenario,
  };
}
