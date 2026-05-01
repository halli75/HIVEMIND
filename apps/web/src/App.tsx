import { useEffect, useMemo, useRef, useState } from "react";
import type {
  AgentStatus,
  AgentTier,
  Archetype,
  ConnectionBadge,
  LeaderboardEntry,
  RunTranscript,
  SwarmAgent,
  SwarmMetrics,
} from "./types";
import { useSwarmStream } from "./useSwarmStream";
import { ARCHETYPE_COLORS, SwarmGraph } from "./components/SwarmGraph";
import { InferenceMetrics } from "./components/InferenceMetrics";

const CRYSTALLIZE_API_URL =
  (import.meta.env.VITE_HIVEMIND_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

type CrystallizedAgent = {
  token_id: number;
  tx_hash: string;
  storage_ref: string;
  archetype: string | null;
  composite_score: number | null;
  owner: string;
  chain?: string;
  explorer?: string | null;
};

const TX_EXPLORERS = {
  zerog: (hash: string) => `https://chainscan-galileo.0g.ai/tx/${hash}`,
  sepolia: (hash: string) => `https://sepolia.etherscan.io/tx/${hash}`,
};

const explorerFor = (entry: CrystallizedAgent) => {
  if (entry.explorer) return entry.explorer;
  if (entry.storage_ref.startsWith("mock://")) return null;
  if (entry.chain === "sepolia") return TX_EXPLORERS.sepolia(entry.tx_hash);
  if (entry.chain === "0g-galileo" || entry.storage_ref.startsWith("0g://")) {
    return TX_EXPLORERS.zerog(entry.tx_hash);
  }
  return null;
};

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

const SCENARIO_PRESETS: { label: string; text: string }[] = [
  {
    label: "🌊 Liquidity Crunch",
    text: "USDC liquidity drains 40% on Uniswap Sepolia within two blocks. Stable pools thin out, slippage triples, and arbitrageurs race to rebalance positions before quotes go stale.",
  },
  {
    label: "📉 20% ETH Crash",
    text: "ETH spot price drops 20% in five minutes after a major exchange outage. Funding rates spike, leveraged positions unwind, and conservative agents must de-risk into stablecoins.",
  },
  {
    label: "⚡ Gas Spike",
    text: "An NFT mint floods the mempool — base fee jumps from 8 gwei to 240 gwei for three blocks. Gas-aware agents must reprice or wait; impatient agents lose to slippage.",
  },
];

function formatComposite(score: number | null): string {
  if (score === null) return "—";
  if (score >= 0 && score <= 1) return `${(score * 100).toFixed(1)}%`;
  return score.toFixed(2);
}

function CrystallizePanel({
  simulationRunId,
  apiAvailable,
}: {
  simulationRunId: string;
  apiAvailable: boolean;
}) {
  const [isCrystallizing, setIsCrystallizing] = useState(false);
  const [results, setResults] = useState<CrystallizedAgent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [glow, setGlow] = useState(false);

  useEffect(() => {
    if (results && results.length > 0) {
      setGlow(true);
      const handle = window.setTimeout(() => setGlow(false), 2000);
      return () => window.clearTimeout(handle);
    }
  }, [results]);

  const handleCrystallize = async () => {
    if (!CRYSTALLIZE_API_URL) {
      setError("VITE_HIVEMIND_API_URL is not configured.");
      return;
    }
    setIsCrystallizing(true);
    setError(null);
    try {
      const response = await fetch(`${CRYSTALLIZE_API_URL}/crystallize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ simulation_run_id: simulationRunId, top_n: 1 }),
      });
      if (!response.ok) {
        throw new Error(`POST /crystallize returned ${response.status}`);
      }
      const data = (await response.json()) as { crystallized: CrystallizedAgent[] };
      setResults(data.crystallized);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsCrystallizing(false);
    }
  };

  const handleCopy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  const winner = results && results.length > 0 ? results[0] : null;
  const explorerUrl = winner ? explorerFor(winner) : null;
  const archetypeKey = (winner?.archetype ?? "") as Archetype;
  const archetypeColor = ARCHETYPE_COLORS[archetypeKey] ?? "#888888";

  return (
    <section
      className={`panel crystallize-panel hero${glow ? " minted-glow" : ""}`}
      aria-labelledby="crystallize-heading"
    >
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Winner crystallization</p>
          <h2 id="crystallize-heading">Mint winning agent as iNFT</h2>
        </div>
        {!winner ? (
          <span className={`connection-pill ${apiAvailable ? "live" : "mock"}`}>
            {apiAvailable ? "Ready to mint" : "API offline"}
          </span>
        ) : (
          <span className="connection-pill live">Minted</span>
        )}
      </div>

      {!winner ? (
        <div className="crystallize-cta">
          <button
            type="button"
            className="primary-button primary-large hero-button"
            onClick={() => void handleCrystallize()}
            disabled={isCrystallizing || !apiAvailable}
          >
            {isCrystallizing ? "Crystallizing…" : "Crystallize Winner"}
          </button>
          {error ? <p className="connection-error">{error}</p> : null}
        </div>
      ) : (
        <div className="crystallize-success">
          <div className="minted-badge">✓ MINTED</div>
          <div className="minted-stats">
            <div className="minted-stat">
              <span>Token ID</span>
              <strong className="minted-token">#{winner.token_id}</strong>
            </div>
            <div className="minted-stat">
              <span>Archetype</span>
              <strong className="minted-archetype">
                <span className="archetype-dot" style={{ background: archetypeColor }} />
                {winner.archetype ?? "unknown"}
              </strong>
            </div>
            <div className="minted-stat">
              <span>Composite</span>
              <strong className="minted-composite">{formatComposite(winner.composite_score)}</strong>
            </div>
          </div>
          {explorerUrl ? (
            <a
              className="primary-button primary-large explorer-link"
              href={explorerUrl}
              target="_blank"
              rel="noreferrer"
            >
              View on 0G Chainscan ↗
            </a>
          ) : null}
          <div className="tx-hash-row">
            <span>Tx</span>
            <code>{winner.tx_hash}</code>
            <button
              type="button"
              className="copy-button"
              onClick={() => void handleCopy(winner.tx_hash)}
              aria-label="Copy transaction hash"
            >
              {copied ? "✓ Copied" : "Copy"}
            </button>
          </div>
          <div className="tx-hash-row">
            <span>Storage</span>
            <code>{winner.storage_ref}</code>
          </div>
        </div>
      )}
    </section>
  );
}

function ScenarioPanel({
  scenario,
  onScenarioChange,
  onRunScenario,
  agentCount,
  onAgentCountChange,
  isRunningScenario,
}: {
  scenario: string;
  onScenarioChange: (value: string) => void;
  onRunScenario: () => void;
  agentCount: number;
  onAgentCountChange: (value: number) => void;
  isRunningScenario: boolean;
}) {
  return (
    <section className="panel scenario-panel" aria-labelledby="scenario-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Scenario injection</p>
          <h2 id="scenario-heading">Market shock prompt</h2>
        </div>
      </div>
      <div className="scenario-presets">
        {SCENARIO_PRESETS.map((preset) => (
          <button
            type="button"
            key={preset.label}
            className="preset-chip"
            onClick={() => onScenarioChange(preset.text)}
          >
            {preset.label}
          </button>
        ))}
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
      <div className="run-row run-row-full">
        <button
          type="button"
          className="primary-button primary-large"
          onClick={onRunScenario}
          disabled={isRunningScenario}
        >
          {isRunningScenario ? "Running…" : "Run Scenario"}
        </button>
      </div>
    </section>
  );
}

function ConnectionStatusLine({
  badges,
  error,
}: {
  badges: ConnectionBadge[];
  error: string | null;
}) {
  const visibleBadges = badges.filter((badge) => !badge.label.toLowerCase().startsWith("api"));

  return (
    <section className="panel status-line-panel" aria-labelledby="badges-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Connections</p>
          <h2 id="badges-heading">Runtime sources</h2>
        </div>
      </div>
      <div className="status-line">
        {visibleBadges.map((badge, index) => (
          <span className={`status-line-item ${badge.tone}`} key={badge.label}>
            <span className="status-line-dot" aria-hidden />
            <span>{badge.label}</span>
            {index < visibleBadges.length - 1 ? (
              <span className="status-line-sep" aria-hidden>
                ·
              </span>
            ) : null}
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
    ["AXL nodes online", metrics.axlNodesOnline.toLocaleString()],
    ["AXL latest type", metrics.axlLastMessageType],
    [
      "AXL p50 latency",
      metrics.axlP50LatencyMs === null ? "pending" : `${metrics.axlP50LatencyMs.toFixed(1)} ms`,
    ],
    [
      "AXL p95 latency",
      metrics.axlP95LatencyMs === null ? "pending" : `${metrics.axlP95LatencyMs.toFixed(1)} ms`,
    ],
    ["AXL failed nodes", metrics.axlFailedNodes.toLocaleString()],
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
    ["AXL nodes online", transcript.axlNodesOnline.toLocaleString()],
    ["AXL latest type", transcript.axlLastMessageType],
    ["AXL p50 latency", transcript.axlP50LatencyMs],
    ["AXL p95 latency", transcript.axlP95LatencyMs],
    ["AXL transcript path", transcript.axlTranscriptPath],
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
        {entries.map((entry) => {
          const isFirst = entry.rank === 1;
          const pnlClass = entry.pnl >= 0 ? "pnl-positive" : "pnl-negative";
          const pnlPrefix = entry.pnl >= 0 ? "+" : "";
          return (
            <div
              className={`table-row${isFirst ? " rank-one" : ""}`}
              role="row"
              key={entry.agentId}
            >
              <span className="rank-cell">
                {isFirst ? <span className="rank-trophy" aria-hidden>🏆</span> : null}
                <span>#{entry.rank}</span>
              </span>
              <strong>{entry.agentId}</strong>
              <span>{entry.strategy}</span>
              <span>{entry.tier}</span>
              <span>{entry.score.toFixed(1)}</span>
              <span className={pnlClass}>
                {pnlPrefix}
                {entry.pnl.toFixed(2)}%
              </span>
              <span>{entry.risk.toFixed(2)}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function MockBanner({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div className="mock-banner" role="status">
      <span className="mock-banner-text">
        ⚡ Running on mock data — connect backend for live swarm
      </span>
      <button
        type="button"
        className="mock-banner-close"
        onClick={onDismiss}
        aria-label="Dismiss banner"
      >
        ×
      </button>
    </div>
  );
}

export function App() {
  const [scenario, setScenario] = useState(SCENARIO_PRESETS[0].text);
  const [agentCount, setAgentCount] = useState(250);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const {
    agents,
    metrics,
    leaderboard,
    tick,
    mode,
    badges,
    transcript,
    axlMessages,
    totalAgentCount,
    inferenceBudget,
    isRunningScenario,
    error,
    runScenario,
  } = useSwarmStream(agentCount, scenario);

  const previousModeRef = useRef(mode);
  useEffect(() => {
    if (mode === "api" && previousModeRef.current === "mock") {
      setBannerDismissed(false);
    }
    previousModeRef.current = mode;
  }, [mode]);

  const showMockBanner = mode === "mock" && !bannerDismissed;

  return (
    <main className="app-shell">
      {showMockBanner ? <MockBanner onDismiss={() => setBannerDismissed(true)} /> : null}
      <header className="topbar">
        <div>
          <p className="eyebrow">HIVEMIND demo console</p>
          <h1>DeFi swarm operations</h1>
        </div>
        {mode === "api" ? (
          <div className="topbar-status">
            <span className="live-dot" />
            API WebSocket connected
          </div>
        ) : null}
      </header>

      <div className="dashboard-grid">
        <div className="left-stack">
          <ScenarioPanel
            agentCount={agentCount}
            isRunningScenario={isRunningScenario}
            onAgentCountChange={setAgentCount}
            onRunScenario={() => void runScenario(scenario)}
            onScenarioChange={setScenario}
            scenario={scenario}
          />
          <ConnectionStatusLine badges={badges} error={error} />
          <TierStatusPanel agents={agents} />
          <InferenceMetrics budget={inferenceBudget} />
        </div>
        <SwarmGraph
          agents={agents}
          axlMessages={axlMessages}
          tick={tick}
          totalAgentCount={totalAgentCount}
          totalAxlMessages={metrics.axlMessages}
        />
        <div className="right-stack">
          <CrystallizePanel
            simulationRunId={transcript.latestScenario || "manual"}
            apiAvailable={mode === "api"}
          />
          <MetricPanel metrics={metrics} mode={mode} />
          <TranscriptPanel transcript={transcript} />
          <Leaderboard entries={leaderboard} />
        </div>
      </div>
    </main>
  );
}
