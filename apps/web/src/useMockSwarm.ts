import { useEffect, useMemo, useState } from "react";
import type { AgentStatus, AgentTier, LeaderboardEntry, SwarmAgent, SwarmMetrics } from "./types";

const STRATEGIES = [
  "Volatility mean reversion",
  "Stable pool arbitrage",
  "Liquidity depth scout",
  "Gas-aware execution",
  "Momentum hedge",
  "Oracle drift monitor",
];

const tierForIndex = (index: number): AgentTier => {
  if (index % 11 === 0) return "T1";
  if (index % 4 === 0) return "T2";
  return "T3";
};

const statusForIndex = (index: number): AgentStatus => {
  if (index === 0) return "winner";
  if (index % 17 === 0) return "fallback";
  if (index % 9 === 0) return "queued";
  return "running";
};

const createAgents = (count: number): SwarmAgent[] =>
  Array.from({ length: count }, (_, index) => {
    const ring = Math.sqrt(index / count);
    const angle = index * 2.399963 + (index % 7) * 0.02;
    const score = 52 + ((index * 37) % 480) / 10;

    return {
      id: `agent-${String(index + 1).padStart(3, "0")}`,
      x: 50 + Math.cos(angle) * ring * 46,
      y: 50 + Math.sin(angle) * ring * 42,
      tier: tierForIndex(index),
      status: statusForIndex(index),
      score,
      confidence: 0.52 + (((index * 19) % 44) / 100),
      strategy: STRATEGIES[index % STRATEGIES.length],
    };
  });

const latestReceipt = (tick: number) =>
  tick < 7 ? "pending Sepolia quote" : `0x7f3a...${(9120 + tick).toString(16)}`;

export function useMockSwarm(agentCount: number, scenario: string) {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const interval = window.setInterval(() => setTick((value) => value + 1), 1400);
    return () => window.clearInterval(interval);
  }, []);

  const agents = useMemo(() => {
    const scenarioWeight = scenario.length % 13;

    return createAgents(agentCount).map((agent, index) => {
      const pulse = Math.sin((tick + index) / 4) * 2.4;
      const score = Math.min(99.7, Math.max(34, agent.score + pulse + scenarioWeight));

      return {
        ...agent,
        score,
        confidence: Math.min(0.99, agent.confidence + (scenarioWeight / 100)),
        x: Math.min(97, Math.max(3, agent.x + Math.sin((tick + index) / 12) * 0.9)),
        y: Math.min(97, Math.max(3, agent.y + Math.cos((tick + index) / 13) * 0.9)),
      };
    });
  }, [agentCount, scenario, tick]);

  const metrics: SwarmMetrics = useMemo(() => {
    const fallbackCount = agents.filter((agent) => agent.status === "fallback").length;

    return {
      axlMessages: 1284 + tick * 21 + scenario.length,
      zeroGInferenceCalls: 312 + tick * 5 + Math.floor(scenario.length / 8),
      aiqSize: 4096 + agentCount * 18 + tick * 7,
      fallbackCount,
      latestSwapReceipt: latestReceipt(tick),
    };
  }, [agentCount, agents, scenario.length, tick]);

  const leaderboard: LeaderboardEntry[] = useMemo(
    () =>
      [...agents]
        .sort((a, b) => b.score - a.score)
        .slice(0, 6)
        .map((agent, index) => ({
          rank: index + 1,
          agentId: agent.id,
          strategy: agent.strategy,
          tier: agent.tier,
          score: agent.score,
          pnl: 1.8 + (agent.score - 50) / 12,
          risk: Math.max(0.9, 6.8 - agent.confidence * 4.2),
        })),
    [agents],
  );

  return { agents, metrics, leaderboard, tick };
}
