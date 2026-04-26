import { useMemo, useState } from "react";
import type {
  AgentStatus,
  AgentTier,
  ConnectionBadge,
  LeaderboardEntry,
  RunTranscript,
  SwarmAgent,
  SwarmMetrics,
} from "./types";
import { useSwarmStream } from "./useSwarmStream";

const tierLabels: Record<AgentTier, string> = {
  T1: "Tier 1 / 0G active",
  T2: "Tier 2 / local model",
  T3: "Tier 3 / heuristic",
};

const statusLabels: Record<AgentStatus, string> = {
  running: "Running",
  queued: "Queued",
  fallback: "Fallback",
  winner: "Winner",
};

function ScenarioPanel({
  scenario,
  onScenarioChange,
  onRunScenario,
  agentCount,
  onAgentCountChange,
  isRunningScenario,
  mode,
}: {
  scenario: string;
  onScenarioChange: (value: string) => void;
  onRunScenario: () => void;
  agentCount: number;
  onAgentCountChange: (value: number) => void;
  isRunningScenario: boolean;
  mode: "api" | "mock";
}) {
  return (
    <section className="panel scenario-panel" aria-labelledby="scenario-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Scenario injection</p>
          <h2 id="scenario-heading">Market shock prompt</h2>
        </div>
        <span className={`connection-pill ${mode}`}>{mode === "api" ? "POST /scenario ready" : "Mock fallback"}</span>
      </div>
      <textarea
        value={scenario}
        onChange={(event) => onScenarioChange(event.target.value)}
        aria-label="Scenario text"
        spellCheck="true"
      />
      <div className="control-row">
        <label htmlFor="agent-count">Agents</label>
        <input
          id="agent-count"
          min="100"
          max="500"
          step="25"
          type="range"
          value={agentCount}
          onChange={(event) => onAgentCountChange(Number(event.target.value))}
        />
        <strong>{agentCount}</strong>
      </div>
      <div className="run-row">
        <button type="button" onClick={onRunScenario} disabled={isRunningScenario}>
          {isRunningScenario ? "Running..." : "Run Scenario"}
        </button>
      </div>
    </section>
  );
}

function ConnectionBadges({ badges, error }: { badges: ConnectionBadge[]; error: string | null }) {
  return (
    <section className="panel badges-panel" aria-labelledby="badges-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Connections</p>
          <h2 id="badges-heading">Runtime sources</h2>
        </div>
      </div>
      <div className="badge-grid">
        {badges.map((badge) => (
          <span className={`connection-badge ${badge.tone}`} key={badge.label}>
            {badge.label}
          </span>
        ))}
      </div>
      {error ? <p className="connection-error">{error}</p> : null}
    </section>
  );
}

function MetricPanel({ metrics, mode }: { metrics: SwarmMetrics; mode: "api" | "mock" }) {
  const items = [
    ["AXL messages", metrics.axlMessages.toLocaleString()],
    ["0G inference calls", metrics.zeroGInferenceCalls.toLocaleString()],
    ["AIQ size", `${metrics.aiqSize.toLocaleString()} kb`],
    ["Fallback count", metrics.fallbackCount.toLocaleString()],
    ["Latest swap receipt", metrics.latestSwapReceipt],
  ];

  return (
    <section className="panel metrics-panel" aria-labelledby="metrics-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Runtime telemetry</p>
          <h2 id="metrics-heading">{mode === "api" ? "Backend counters" : "Demo counters"}</h2>
        </div>
      </div>
      <div className="metric-grid">
        {items.map(([label, value]) => (
          <div className="metric" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function TranscriptPanel({ transcript }: { transcript: RunTranscript }) {
  const rows = [
    ["Latest scenario", transcript.latestScenario],
    ["Latest AXL messages", transcript.axlMessageCount.toLocaleString()],
    ["Latest 0G storage URI", transcript.zeroGStorageUri],
    ["Latest 0G hash", transcript.zeroGStorageHash],
    ["Latest iNFT token", transcript.inftToken],
    ["Latest iNFT local address", transcript.inftAddress],
    ["Latest Uniswap quote", transcript.uniswapQuote],
    ["Latest Uniswap swap receipt", transcript.uniswapSwapReceipt],
  ];

  return (
    <section className="panel transcript-panel" aria-labelledby="transcript-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Run transcript</p>
          <h2 id="transcript-heading">Proof fields</h2>
        </div>
      </div>
      <div className="transcript-list">
        {rows.map(([label, value]) => (
          <div className="transcript-row" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function TierStatusPanel({ agents }: { agents: SwarmAgent[] }) {
  const tierCounts = useMemo(
    () =>
      (["T1", "T2", "T3"] as AgentTier[]).map((tier) => ({
        tier,
        count: agents.filter((agent) => agent.tier === tier).length,
      })),
    [agents],
  );

  const statusCounts = useMemo(
    () =>
      (["running", "queued", "fallback", "winner"] as AgentStatus[]).map((status) => ({
        status,
        count: agents.filter((agent) => agent.status === status).length,
      })),
    [agents],
  );

  return (
    <section className="panel compact-panel" aria-labelledby="tier-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Inference routing</p>
          <h2 id="tier-heading">Tier and status</h2>
        </div>
      </div>
      <div className="tier-list">
        {tierCounts.map(({ tier, count }) => (
          <div className="tier-row" key={tier}>
            <span className={`tier-dot ${tier.toLowerCase()}`} />
            <span>{tierLabels[tier]}</span>
            <strong>{count}</strong>
          </div>
        ))}
      </div>
      <div className="status-grid">
        {statusCounts.map(({ status, count }) => (
          <div className={`status-chip ${status}`} key={status}>
            <span>{statusLabels[status]}</span>
            <strong>{count}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function SwarmGraph({ agents, tick }: { agents: SwarmAgent[]; tick: number }) {
  const topAgents = useMemo(
    () => [...agents].sort((a, b) => b.score - a.score).slice(0, 12),
    [agents],
  );

  return (
    <section className="panel graph-panel" aria-labelledby="graph-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Swarm execution</p>
          <h2 id="graph-heading">{agents.length} agents reacting</h2>
        </div>
        <span className="tick">tick {tick}</span>
      </div>
      <svg className="swarm-svg" viewBox="0 0 100 100" role="img" aria-label="Graph-like swarm visualization">
        <defs>
          <radialGradient id="winner-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#f8f1a5" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#f8f1a5" stopOpacity="0" />
          </radialGradient>
        </defs>
        {topAgents.slice(1).map((agent) => (
          <line
            className="agent-edge"
            key={`edge-${agent.id}`}
            x1={topAgents[0]?.x ?? 50}
            x2={agent.x}
            y1={topAgents[0]?.y ?? 50}
            y2={agent.y}
          />
        ))}
        {agents.map((agent) => (
          <circle
            className={`agent-node ${agent.tier.toLowerCase()} ${agent.status}`}
            cx={agent.x}
            cy={agent.y}
            key={agent.id}
            r={agent.status === "winner" ? 1.55 : agent.tier === "T1" ? 1.05 : 0.72}
          />
        ))}
        {topAgents[0] ? (
          <circle cx={topAgents[0].x} cy={topAgents[0].y} fill="url(#winner-glow)" r="6" />
        ) : null}
      </svg>
    </section>
  );
}

function Leaderboard({ entries }: { entries: LeaderboardEntry[] }) {
  return (
    <section className="panel leaderboard-panel" aria-labelledby="leaderboard-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Strategy selection</p>
          <h2 id="leaderboard-heading">Leaderboard</h2>
        </div>
      </div>
      <div className="leaderboard-table" role="table" aria-label="Agent leaderboard">
        <div className="table-row table-head" role="row">
          <span>Rank</span>
          <span>Agent</span>
          <span>Strategy</span>
          <span>Tier</span>
          <span>Score</span>
          <span>PNL</span>
          <span>Risk</span>
        </div>
        {entries.map((entry) => (
          <div className="table-row" role="row" key={entry.agentId}>
            <span>#{entry.rank}</span>
            <strong>{entry.agentId}</strong>
            <span>{entry.strategy}</span>
            <span>{entry.tier}</span>
            <span>{entry.score.toFixed(1)}</span>
            <span>{entry.pnl.toFixed(2)}%</span>
            <span>{entry.risk.toFixed(2)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export function App() {
  const [scenario, setScenario] = useState(
    "ETH volatility spikes 6%, USDC liquidity thins on Sepolia, and gas rises for three blocks. Re-rank agents for a conservative swap.",
  );
  const [agentCount, setAgentCount] = useState(250);
  const { agents, metrics, leaderboard, tick, mode, badges, transcript, isRunningScenario, error, runScenario } =
    useSwarmStream(agentCount, scenario);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">HIVEMIND demo console</p>
          <h1>DeFi swarm operations</h1>
        </div>
        <div className="topbar-status">
          <span className={`live-dot ${mode}`} />
          {mode === "api" ? "API WebSocket connected" : "Mock fallback active"}
        </div>
      </header>

      <div className="dashboard-grid">
        <div className="left-stack">
          <ScenarioPanel
            agentCount={agentCount}
            isRunningScenario={isRunningScenario}
            mode={mode}
            onAgentCountChange={setAgentCount}
            onRunScenario={() => void runScenario(scenario)}
            onScenarioChange={setScenario}
            scenario={scenario}
          />
          <ConnectionBadges badges={badges} error={error} />
          <TierStatusPanel agents={agents} />
        </div>
        <SwarmGraph agents={agents} tick={tick} />
        <div className="right-stack">
          <MetricPanel metrics={metrics} mode={mode} />
          <TranscriptPanel transcript={transcript} />
          <Leaderboard entries={leaderboard} />
        </div>
      </div>
    </main>
  );
}
