import type { LeaderboardEntry, SwarmAgent } from "../types";
import {
  ACTION_COLORS,
  ACTION_LABELS,
  ARCHETYPE_COLORS,
  ARCHETYPE_LABELS,
} from "./SwarmGraph";

const ARCHETYPE_BIOS: Record<string, string> = {
  whale:
    "Accumulates positions during macro dislocations. High conviction, low frequency. Moves markets.",
  degen:
    "High-velocity speculation on momentum signals. Embraces volatility. Exits fast or exits poor.",
  lp_provider:
    "Optimizes fee income vs impermanent loss. Concentrates liquidity near price. Rebalances on IL spikes.",
  arbitrageur:
    "Exploits cross-venue price discrepancies. Microsecond latency. Spread-hunting across pools.",
  governance_voter:
    "Stake-weighted protocol votes. Reads social graph consensus. Long-horizon governance alpha.",
  stablecoin_arb:
    "Monitors peg deviations. Farms depeg events for low-risk yield. Reacts to liquidity drains.",
  mev_searcher:
    "Extracts maximal extractable value from mempool. Front-runs large intents. High gas tolerance.",
};

const TIER_DESCRIPTIONS: Record<string, string> = {
  T1: "0G Compute · live LLM inference",
  T2: "Local model · structured ruleset",
  T3: "Heuristic · zero inference cost",
};

type InferenceBadge = {
  label: string;
  color: string;
  glow: string;
  detail: string;
};

const inferenceBadgeFor = (
  source: string | undefined,
  model: string | undefined,
): InferenceBadge => {
  const normalized = (source ?? "").toLowerCase();
  if (normalized.startsWith("0g")) {
    return {
      label: "0G LIVE",
      color: "#00ffaa",
      glow: "#00ffaa",
      detail: model ? model : "0g compute",
    };
  }
  if (normalized.includes("fallback")) {
    return {
      label: "FALLBACK",
      color: "#ff7700",
      glow: "#ff7700",
      detail: model ? `${model} (degraded)` : "0g unreachable",
    };
  }
  if (normalized === "local" || normalized === "local_model") {
    return {
      label: "LOCAL",
      color: "#00bfff",
      glow: "#00bfff",
      detail: model || "local model",
    };
  }
  if (normalized === "heuristic" || normalized === "" || normalized === "rule") {
    return {
      label: "HEURISTIC",
      color: "#7a9a8a",
      glow: "#5a7a6a",
      detail: "deterministic rule",
    };
  }
  return {
    label: normalized.toUpperCase(),
    color: "#cc77ff",
    glow: "#cc77ff",
    detail: model || normalized,
  };
};

function StatCell({
  label,
  value,
  accent,
  mono,
}: {
  label: string;
  value: string;
  accent?: string;
  mono?: boolean;
}) {
  return (
    <div className="adp-stat">
      <span className="adp-stat-label">{label}</span>
      <strong
        className={`adp-stat-value${mono ? " adp-stat-mono" : ""}`}
        style={accent ? { color: accent, textShadow: `0 0 12px ${accent}88` } : undefined}
      >
        {value}
      </strong>
    </div>
  );
}

export function AgentDetailPanel({
  agent,
  leaderboard,
  onClose,
}: {
  agent: SwarmAgent | null;
  leaderboard: LeaderboardEntry[];
  onClose: () => void;
}) {
  const visible = agent !== null;
  const sourceId = agent?.sourceId ?? agent?.id ?? "";
  const rankIndex = agent
    ? leaderboard.findIndex((entry) => entry.agentId === sourceId)
    : -1;
  const rank = rankIndex >= 0 ? rankIndex + 1 : null;
  const archetypeKey = (agent?.archetype ?? "degen") as keyof typeof ARCHETYPE_COLORS;
  const archetypeColor = ARCHETYPE_COLORS[archetypeKey] ?? "#888";
  const archetypeLabel = ARCHETYPE_LABELS[archetypeKey] ?? archetypeKey;
  const action = agent?.action ?? "hold";
  const actionColor = ACTION_COLORS[action] ?? "#4a6060";
  const actionLabel = ACTION_LABELS[action] ?? action.toUpperCase();
  const pnlBps = agent?.pnl_bps ?? 0;
  const pnlPct = pnlBps / 100;
  const pnlPositive = pnlPct >= 0;
  const aiq = agent?.aiq ?? 0;
  const confidence = agent?.confidence ?? 0;
  const confidencePct = Math.min(100, Math.max(0, confidence * 100));
  const aiqPct = Math.min(100, Math.max(0, aiq * 100));
  const score = agent?.score ?? 0;
  const tier = agent?.tier ?? "T3";
  const status = agent?.status ?? "running";
  const rationale =
    agent?.rationale ??
    "No rationale available — agent has not surfaced an explanation for its current action.";
  const bio = ARCHETYPE_BIOS[archetypeKey] ?? "Adaptive on-chain agent.";
  const inferenceBadge = inferenceBadgeFor(agent?.inferenceSource, agent?.model);

  return (
    <aside
      className={`agent-detail-panel${visible ? " visible" : ""}`}
      aria-hidden={!visible}
    >
      <div className="adp-scanline" aria-hidden />
      <header className="adp-header">
        <div className="adp-header-top">
          <span
            className="adp-archetype-pill"
            style={{
              borderColor: archetypeColor,
              color: archetypeColor,
              boxShadow: `0 0 14px ${archetypeColor}55`,
            }}
          >
            <span
              className="adp-archetype-dot"
              style={{ background: archetypeColor }}
            />
            {archetypeLabel}
          </span>
          <button
            type="button"
            className="adp-close"
            onClick={onClose}
            aria-label="Close agent detail"
          >
            ✕
          </button>
        </div>
        <div className="adp-id-row">
          <span className="adp-id-eyebrow">AGENT_ID</span>
          <h2 className="adp-id">{agent?.id ?? "—"}</h2>
        </div>
        <div className="adp-meta-row">
          <span className="adp-meta">
            <span className="adp-meta-label">TIER</span>
            <span className="adp-meta-value">{tier}</span>
          </span>
          <span className="adp-meta">
            <span className="adp-meta-label">STATUS</span>
            <span className={`adp-meta-value adp-status-${status}`}>{status.toUpperCase()}</span>
          </span>
          <span className="adp-meta">
            <span className="adp-meta-label">RANK</span>
            <span className="adp-meta-value">{rank !== null ? `#${rank}` : "—"}</span>
          </span>
        </div>
      </header>

      <section className="adp-section adp-action-section">
        <p className="adp-section-eyebrow">CURRENT ACTION</p>
        <div
          className="adp-action-card"
          style={{
            borderColor: actionColor,
            boxShadow: `0 0 18px ${actionColor}55, inset 0 0 24px ${actionColor}18`,
          }}
        >
          <span
            className="adp-action-glyph"
            style={{ color: actionColor, textShadow: `0 0 14px ${actionColor}` }}
          >
            ▸
          </span>
          <div className="adp-action-text">
            <strong style={{ color: actionColor, textShadow: `0 0 10px ${actionColor}aa` }}>
              {actionLabel}
            </strong>
            <span className="adp-action-strategy">{agent?.strategy ?? "—"}</span>
          </div>
        </div>
      </section>

      <section className="adp-section">
        <div className="adp-rationale-head">
          <p className="adp-section-eyebrow">RATIONALE</p>
          <span
            className="adp-inference-badge"
            style={{
              borderColor: inferenceBadge.color,
              color: inferenceBadge.color,
              boxShadow: `0 0 10px ${inferenceBadge.glow}55, inset 0 0 8px ${inferenceBadge.glow}22`,
            }}
            title={inferenceBadge.detail}
          >
            <span
              className="adp-inference-dot"
              style={{ background: inferenceBadge.color, boxShadow: `0 0 6px ${inferenceBadge.color}` }}
            />
            {inferenceBadge.label}
          </span>
        </div>
        <blockquote
          className="adp-rationale"
          style={{ borderLeftColor: inferenceBadge.color }}
        >
          <span
            className="adp-rationale-glyph"
            aria-hidden
            style={{ color: inferenceBadge.color, textShadow: `0 0 8px ${inferenceBadge.color}` }}
          >
            ❯
          </span>
          <p>{rationale}</p>
        </blockquote>
        {inferenceBadge.detail ? (
          <p className="adp-inference-detail">
            <span>via</span>
            <code>{inferenceBadge.detail}</code>
          </p>
        ) : null}
      </section>

      <section className="adp-section">
        <p className="adp-section-eyebrow">TELEMETRY</p>
        <div className="adp-stat-grid">
          <StatCell label="SCORE" value={score.toFixed(1)} accent="#00ffaa" />
          <StatCell
            label="P&L"
            value={`${pnlPositive ? "+" : ""}${pnlPct.toFixed(2)}%`}
            accent={pnlPositive ? "#00ffaa" : "#ff3355"}
          />
          <StatCell label="AIQ" value={aiq.toFixed(2)} accent="#00bfff" />
          <StatCell
            label="CONF"
            value={`${(confidence * 100).toFixed(0)}%`}
            accent="#cc77ff"
          />
        </div>
        <div className="adp-bar-block">
          <div className="adp-bar-row">
            <span>CONFIDENCE</span>
            <span>{confidencePct.toFixed(0)}%</span>
          </div>
          <div className="adp-bar">
            <span
              className="adp-bar-fill"
              style={{
                width: `${confidencePct}%`,
                background: "linear-gradient(90deg, #00ffaa, #cc77ff)",
                boxShadow: "0 0 12px rgba(0, 255, 170, 0.5)",
              }}
            />
          </div>
          <div className="adp-bar-row">
            <span>AIQ ALLOC</span>
            <span>{aiqPct.toFixed(0)}%</span>
          </div>
          <div className="adp-bar">
            <span
              className="adp-bar-fill"
              style={{
                width: `${aiqPct}%`,
                background: "linear-gradient(90deg, #00bfff, #00ffaa)",
                boxShadow: "0 0 12px rgba(0, 191, 255, 0.5)",
              }}
            />
          </div>
        </div>
      </section>

      <section className="adp-section">
        <p className="adp-section-eyebrow">PERSONA / {archetypeLabel.toUpperCase()}</p>
        <p className="adp-bio">{bio}</p>
        <p className="adp-tier-note">{TIER_DESCRIPTIONS[tier]}</p>
      </section>

      <footer className="adp-footer">
        <span className="adp-footer-tag">SOURCE</span>
        <code className="adp-footer-code">{sourceId}</code>
      </footer>
    </aside>
  );
}
