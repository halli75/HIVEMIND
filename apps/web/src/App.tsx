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
import { AgentDetailPanel } from "./components/AgentDetailPanel";

const HIVEMIND_API_URL =
  (import.meta.env.VITE_HIVEMIND_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

type MintedAgent = {
  token_id: number | null;
  tx_hash: string | null;
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

type MintResponse = {
  status: string;
  token_id?: number | null;
  tx_hash?: string | null;
  tx_url?: string | null;
  storage_url?: string | null;
  storage_uri?: string | null;
  storage_hash?: string | null;
  contract?: string | null;
  proof?: {
    token_id?: number | null;
    tx_hash?: string | null;
    storage_uri?: string | null;
    storage_hash?: string | null;
    contract_address?: string | null;
    chain?: string | null;
    tx_explorer?: string | null;
  };
};

const errorMessageFromResponse = async (response: Response) => {
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") {
      const typed = detail as Record<string, unknown>;
      const status = typeof typed.status === "string" ? typed.status : `HTTP ${response.status}`;
      const message = typeof typed.message === "string" ? typed.message : response.statusText;
      return `${status}: ${message}`;
    }
  } catch {
    // Fall through to the generic status message.
  }
  return `POST /mint returned ${response.status}`;
};

const explorerFor = (entry: MintedAgent) => {
  if (entry.explorer) return entry.explorer;
  if (!entry.tx_hash) return null;
  if (entry.storage_ref.startsWith("mock://")) return null;
  if (entry.chain === "sepolia") return TX_EXPLORERS.sepolia(entry.tx_hash);
  if (entry.chain === "0g-galileo" || entry.storage_ref.startsWith("0g://")) {
    return TX_EXPLORERS.zerog(entry.tx_hash);
  }
  return null;
};

const tierLabels: Record<AgentTier, string> = {
  T1: "T1 / 0G",
  T2: "T2 / local",
  T3: "T3 / heur",
};

const statusLabels: Record<AgentStatus, string> = {
  running: "Running",
  queued: "Queued",
  fallback: "Fallback",
  winner: "Winner",
};

const DEFAULT_SCENARIO =
  "USDC liquidity drains 40% on Uniswap Sepolia within two blocks. Stable pools thin out, slippage triples, and arbitrageurs race to rebalance positions before quotes go stale.";

function formatComposite(score: number | null): string {
  if (score === null) return "-";
  if (score >= 0 && score <= 1) return `${(score * 100).toFixed(1)}%`;
  return score.toFixed(2);
}

function HudBar({
  badges,
  mode,
  error,
  tick,
  agentCount,
}: {
  badges: ConnectionBadge[];
  mode: "api" | "mock";
  error: string | null;
  tick: number;
  agentCount: number;
}) {
  const visibleBadges = badges.filter((b) => !b.label.toLowerCase().startsWith("api"));
  return (
    <header className="hud-bar">
      <div className="hud-brand">
        <span className="hud-brand-mark">⬢</span>
        <span className="hud-brand-name">HIVEMIND</span>
        <span className="hud-brand-sub">// neural swarm console</span>
      </div>

      <div className="hud-ticker" aria-hidden>
        <div className="hud-ticker-track">
          <span>0G COMPUTE LIVE</span>
          <span>·</span>
          <span>GENSYN AXL MESH</span>
          <span>·</span>
          <span>UNISWAP SEPOLIA</span>
          <span>·</span>
          <span>iNFT CRYSTALLIZER</span>
          <span>·</span>
          <span>SWARM CONSENSUS @ {tick}</span>
          <span>·</span>
          <span>0G COMPUTE LIVE</span>
          <span>·</span>
          <span>GENSYN AXL MESH</span>
          <span>·</span>
          <span>UNISWAP SEPOLIA</span>
          <span>·</span>
          <span>iNFT CRYSTALLIZER</span>
        </div>
      </div>

      <div className="hud-status">
        <span className="hud-stat">
          <span className="hud-stat-label">TICK</span>
          <strong key={tick} className="hud-stat-value">
            {tick.toString().padStart(5, "0")}
          </strong>
        </span>
        <span className="hud-stat">
          <span className="hud-stat-label">AGT</span>
          <strong className="hud-stat-value">{agentCount.toLocaleString()}</strong>
        </span>
        <span className="hud-divider" />
        {mode === "api" ? (
          <span className="hud-badge live">
            <span className="hud-dot" />
            WS
          </span>
        ) : (
          <span className="hud-badge mock">
            <span className="hud-dot" />
            MOCK
          </span>
        )}
        {visibleBadges.map((badge) => (
          <span className={`hud-badge ${badge.tone}`} key={badge.label}>
            <span className="hud-dot" />
            {badge.label}
          </span>
        ))}
        {error ? (
          <span className="hud-badge offline" title={error}>
            <span className="hud-dot" />
            ERR
          </span>
        ) : null}
      </div>
    </header>
  );
}

function MintSection({
  apiAvailable,
  mintConfigured,
  winningEntry,
}: {
  apiAvailable: boolean;
  mintConfigured: boolean;
  winningEntry: LeaderboardEntry | undefined;
}) {
  const [isCrystallizing, setIsCrystallizing] = useState(false);
  const [results, setResults] = useState<MintedAgent[] | null>(null);
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
    if (!HIVEMIND_API_URL) {
      setError("VITE_HIVEMIND_API_URL is not configured.");
      return;
    }
    if (!mintConfigured) {
      setError("INFT_CONTRACT_ADDRESS is not configured on the API.");
      return;
    }
    setIsCrystallizing(true);
    setError(null);
    try {
      const response = await fetch(`${HIVEMIND_API_URL}/mint`, { method: "POST" });
      if (!response.ok) {
        throw new Error(await errorMessageFromResponse(response));
      }
      const data = (await response.json()) as MintResponse;
      setResults([
        {
          token_id: data.token_id ?? data.proof?.token_id ?? null,
          tx_hash: data.tx_hash ?? data.proof?.tx_hash ?? null,
          storage_ref:
            data.storage_uri ??
            data.proof?.storage_uri ??
            data.storage_hash ??
            data.proof?.storage_hash ??
            "pending storage proof",
          archetype: winningEntry?.strategy.split(" / ")[0] ?? null,
          composite_score: winningEntry?.score ?? null,
          owner: data.contract ?? data.proof?.contract_address ?? "",
          chain: data.proof?.chain ?? "0g-galileo",
          explorer: data.tx_url ?? data.proof?.tx_explorer ?? null,
        },
      ]);
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

  const minted = results && results.length > 0 ? results[0] : null;
  const explorerUrl = minted ? explorerFor(minted) : null;
  const archetypeKey = (minted?.archetype ?? "") as Archetype;
  const archetypeColor = ARCHETYPE_COLORS[archetypeKey] ?? "#888888";

  return (
    <div className={`mint-section${glow ? " mint-glow" : ""}`}>
      {!minted ? (
        <div className="mint-cta-row">
          <div className="mint-cta-label">
            <p className="eyebrow">Crystallize winner</p>
            <p className="mint-cta-subtitle">Mint top agent → 0G iNFT</p>
          </div>
          <div className="mint-cta-actions">
            <span className={`mini-pill ${apiAvailable ? "live" : "mock"}`}>
              {apiAvailable ? (mintConfigured ? "READY" : "NOT_CFG") : "API_DOWN"}
            </span>
            <button
              type="button"
              className="primary-button primary-large"
              onClick={() => void handleCrystallize()}
              disabled={isCrystallizing || !apiAvailable || !mintConfigured}
            >
              {isCrystallizing ? "MINTING..." : "▸ MINT WINNER"}
            </button>
          </div>
          {error ? <p className="connection-error mint-error">{error}</p> : null}
        </div>
      ) : (
        <div className="mint-success">
          <div className="mint-success-top">
            <div className="minted-badge">★ MINTED</div>
            <div className="minted-stats">
              <div className="minted-stat">
                <span>TOKEN</span>
                <strong className="minted-token">
                  {minted.token_id === null ? "pending" : `#${minted.token_id}`}
                </strong>
              </div>
              <div className="minted-stat">
                <span>ARCH</span>
                <strong className="minted-archetype">
                  <span className="archetype-dot" style={{ background: archetypeColor }} />
                  {minted.archetype ?? "unknown"}
                </strong>
              </div>
              <div className="minted-stat">
                <span>SCORE</span>
                <strong className="minted-composite">{formatComposite(minted.composite_score)}</strong>
              </div>
            </div>
            {explorerUrl ? (
              <a
                className="primary-button explorer-link"
                href={explorerUrl}
                target="_blank"
                rel="noreferrer"
              >
                ↗ 0G CHAINSCAN
              </a>
            ) : null}
          </div>
          {minted.tx_hash ? (
            <div className="tx-hash-row">
              <span>TX</span>
              <code>{minted.tx_hash}</code>
              <button
                type="button"
                className="copy-button"
                onClick={() => void handleCopy(minted.tx_hash ?? "")}
                aria-label="Copy transaction hash"
              >
                {copied ? "✓" : "⎘"}
              </button>
            </div>
          ) : null}
          <div className="tx-hash-row">
            <span>STO</span>
            <code>{minted.storage_ref}</code>
          </div>
        </div>
      )}
    </div>
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
          <p className="eyebrow">▸ Scenario inject</p>
          <h2 id="scenario-heading">Market shock prompt</h2>
        </div>
      </div>
      <textarea
        value={scenario}
        onChange={(event) => onScenarioChange(event.target.value)}
        aria-label="Scenario text"
        spellCheck="true"
        placeholder="Describe the market shock to inject into the swarm..."
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
          {isRunningScenario ? "▸ RUNNING..." : "▸ EXECUTE SCENARIO"}
        </button>
      </div>
    </section>
  );
}

function CompactMetricsPanel({
  metrics,
  agents,
  mode,
}: {
  metrics: SwarmMetrics;
  agents: SwarmAgent[];
  mode: "api" | "mock";
}) {
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
    <section className="panel compact-metrics" aria-labelledby="metrics-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">▸ Telemetry</p>
          <h2 id="metrics-heading">{mode === "api" ? "Backend ops" : "Demo ops"}</h2>
        </div>
      </div>
      <div className="cm-section">
        <p className="cm-section-eyebrow">TIER ROUTING</p>
        <div className="cm-tier-list">
          {tierCounts.map(({ tier, count }) => (
            <div className="cm-tier-row" key={tier}>
              <span className={`cm-tier-dot ${tier.toLowerCase()}`} />
              <span>{tierLabels[tier]}</span>
              <strong>{count}</strong>
            </div>
          ))}
        </div>
      </div>
      <div className="cm-section">
        <p className="cm-section-eyebrow">STATUS</p>
        <div className="cm-status-grid">
          {statusCounts.map(({ status, count }) => (
            <div className={`cm-status-chip ${status}`} key={status}>
              <span>{statusLabels[status]}</span>
              <strong>{count}</strong>
            </div>
          ))}
        </div>
      </div>
      <div className="cm-section">
        <p className="cm-section-eyebrow">METRICS</p>
        <div className="cm-metric-grid">
          <div className="cm-metric">
            <span>AXL_MSGS</span>
            <strong>{metrics.axlMessages.toLocaleString()}</strong>
          </div>
          <div className="cm-metric">
            <span>NODES</span>
            <strong>{metrics.axlNodesOnline.toLocaleString()}</strong>
          </div>
          <div className="cm-metric">
            <span>P50</span>
            <strong>
              {metrics.axlP50LatencyMs === null ? "—" : `${metrics.axlP50LatencyMs.toFixed(1)}`}
            </strong>
          </div>
          <div className="cm-metric">
            <span>P95</span>
            <strong>
              {metrics.axlP95LatencyMs === null ? "—" : `${metrics.axlP95LatencyMs.toFixed(1)}`}
            </strong>
          </div>
          <div className="cm-metric">
            <span>0G_CALLS</span>
            <strong>{metrics.zeroGInferenceCalls.toLocaleString()}</strong>
          </div>
          <div className="cm-metric">
            <span>FALLBACK</span>
            <strong>{metrics.fallbackCount.toLocaleString()}</strong>
          </div>
        </div>
      </div>
    </section>
  );
}

function TranscriptPanel({ transcript }: { transcript: RunTranscript }) {
  const [open, setOpen] = useState(false);

  const rows = [
    ["Scenario", transcript.latestScenario],
    ["AXL msgs", transcript.axlMessageCount.toLocaleString()],
    ["AXL nodes", transcript.axlNodesOnline.toLocaleString()],
    ["AXL type", transcript.axlLastMessageType],
    ["p50 latency", transcript.axlP50LatencyMs],
    ["p95 latency", transcript.axlP95LatencyMs],
    ["Transcript", transcript.axlTranscriptPath],
    ["0G URI", transcript.zeroGStorageUri],
    ["0G hash", transcript.zeroGStorageHash],
    ["iNFT token", transcript.inftToken],
    ["iNFT addr", transcript.inftAddress],
    ["Uni quote", transcript.uniswapQuote],
    ["Swap rcpt", transcript.uniswapSwapReceipt],
  ];

  return (
    <section className="panel transcript-panel" aria-labelledby="transcript-heading">
      <button
        type="button"
        className="transcript-toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        id="transcript-heading"
      >
        <span>▸ Proof fields</span>
        <span className="transcript-chevron" aria-hidden>
          {open ? "▲" : "▼"}
        </span>
      </button>
      {open ? (
        <div className="transcript-list">
          {rows.map(([label, value]) => (
            <div className="transcript-row" key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function Leaderboard({
  entries,
  onSelectAgent,
  selectedAgentSourceId,
}: {
  entries: LeaderboardEntry[];
  onSelectAgent: (sourceId: string) => void;
  selectedAgentSourceId: string | null;
}) {
  return (
    <section className="panel leaderboard-panel" aria-labelledby="leaderboard-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">▸ Strategy selection</p>
          <h2 id="leaderboard-heading">Leaderboard</h2>
        </div>
      </div>
      <div className="leaderboard-table" role="table" aria-label="Agent leaderboard">
        <div className="table-row table-head" role="row">
          <span>#</span>
          <span>Agent</span>
          <span>Strategy</span>
          <span>Tier</span>
          <span>Score</span>
          <span>PNL</span>
        </div>
        {entries.map((entry) => {
          const isFirst = entry.rank === 1;
          const isSelected = entry.agentId === selectedAgentSourceId;
          const pnlClass = entry.pnl >= 0 ? "pnl-positive" : "pnl-negative";
          const pnlPrefix = entry.pnl >= 0 ? "+" : "";
          return (
            <button
              type="button"
              className={`table-row${isFirst ? " rank-one" : ""}${isSelected ? " selected" : ""}`}
              role="row"
              key={entry.agentId}
              onClick={() => onSelectAgent(entry.agentId)}
            >
              <span className="rank-cell">
                {isFirst ? <span className="rank-trophy" aria-hidden>★</span> : null}
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
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function App() {
  const [scenario, setScenario] = useState(DEFAULT_SCENARIO);
  const [agentCount, setAgentCount] = useState(250);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
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
    isRunningScenario,
    error,
    runScenario,
  } = useSwarmStream(agentCount, scenario);

  const previousModeRef = useRef(mode);
  useEffect(() => {
    previousModeRef.current = mode;
  }, [mode]);

  const selectedAgent = useMemo(
    () => agents.find((a) => a.id === selectedAgentId) ?? null,
    [agents, selectedAgentId],
  );

  const selectedAgentSourceId = selectedAgent?.sourceId ?? null;

  // When user clicks a leaderboard row, find a matching agent in the visual swarm.
  const handleSelectFromLeaderboard = (sourceId: string) => {
    const match = agents.find((a) => a.sourceId === sourceId);
    if (match) setSelectedAgentId(match.id);
  };

  return (
    <main className="app-root">
      <HudBar
        badges={badges}
        mode={mode}
        error={error}
        tick={tick}
        agentCount={totalAgentCount || agents.length}
      />

      <div className="main-area">
        <aside className="left-sidebar">
          <ScenarioPanel
            agentCount={agentCount}
            isRunningScenario={isRunningScenario}
            onAgentCountChange={setAgentCount}
            onRunScenario={() => void runScenario(scenario)}
            onScenarioChange={setScenario}
            scenario={scenario}
          />
          <CompactMetricsPanel metrics={metrics} agents={agents} mode={mode} />
        </aside>

        <section className="graph-viewport">
          <SwarmGraph
            agents={agents}
            axlMessages={axlMessages}
            tick={tick}
            totalAgentCount={totalAgentCount}
            totalAxlMessages={metrics.axlMessages}
            onNodeClick={(nodeId) => setSelectedAgentId(nodeId)}
            selectedNodeId={selectedAgentId}
            onBackgroundClick={() => setSelectedAgentId(null)}
          />
          <AgentDetailPanel
            agent={selectedAgent}
            leaderboard={leaderboard}
            onClose={() => setSelectedAgentId(null)}
          />
        </section>

        <aside className="right-sidebar">
          <Leaderboard
            entries={leaderboard}
            onSelectAgent={handleSelectFromLeaderboard}
            selectedAgentSourceId={selectedAgentSourceId}
          />
          <TranscriptPanel transcript={transcript} />
          <MintSection
            apiAvailable={mode === "api"}
            mintConfigured={
              transcript.inftStatus === "active" || transcript.inftStatus === "minted"
            }
            winningEntry={leaderboard[0]}
          />
        </aside>
      </div>
    </main>
  );
}
