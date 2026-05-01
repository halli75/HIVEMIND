import { useEffect, useMemo, useRef, useState } from "react";
import Graph from "graphology";
import Sigma from "sigma";
import forceAtlas2 from "graphology-layout-forceatlas2";
import { createNodeBorderProgram } from "@sigma/node-border";
import type { Archetype, AxlEdgeMessage, SwarmAgent } from "../types";

export const ARCHETYPE_COLORS: Record<Archetype, string> = {
  whale: "#5b8fc9",
  degen: "#c9a84c",
  lp_provider: "#5aab7a",
  arbitrageur: "#9b7fd4",
  governance_voter: "#8a8880",
  stablecoin_arb: "#4db8c8",
  mev_searcher: "#c96b6b",
};

export const ARCHETYPE_LABELS: Record<Archetype, string> = {
  whale: "Whale",
  degen: "Degen",
  lp_provider: "LP Provider",
  arbitrageur: "Arbitrageur",
  governance_voter: "Governance",
  stablecoin_arb: "Stablecoin Arb",
  mev_searcher: "MEV Searcher",
};

const TIER_SIZES = { T1: 12, T2: 8, T3: 5 } as const;

const WINNER_FILL = "#f3c84a";
const WINNER_BORDER = "#fff2a8";

const MAX_RENDERED_NODES = 500;
const PULSE_DURATION_MS = 400;
const EDGE_DECAY_TICKS = 3;
const CONNECTING_OVERLAY_MS = 3000;

const sampleAgents = (agents: SwarmAgent[], cap: number): SwarmAgent[] => {
  if (agents.length <= cap) return agents;
  const step = agents.length / cap;
  const out: SwarmAgent[] = [];
  for (let i = 0; i < cap; i += 1) {
    out.push(agents[Math.floor(i * step)]);
  }
  return out;
};

function SwarmGraphCanvas({
  agents,
  axlMessages,
  tick,
  winnerId,
}: {
  agents: SwarmAgent[];
  axlMessages: AxlEdgeMessage[];
  tick: number;
  winnerId: string | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const pulseStateRef = useRef<Map<string, number>>(new Map());
  const animationRef = useRef<number | null>(null);
  const winnerIdRef = useRef<string | null>(null);
  const previousWinnerIdRef = useRef<string | null>(null);

  useEffect(() => {
    winnerIdRef.current = winnerId;
  }, [winnerId]);

  useEffect(() => {
    if (!containerRef.current) return;

    const graph = new Graph({ multi: false, type: "directed" });
    graphRef.current = graph;

    const sigma = new Sigma(graph, containerRef.current, {
      renderEdgeLabels: false,
      defaultEdgeColor: "rgba(157, 185, 165, 0.35)",
      labelColor: { color: "#e8dba0" },
      labelSize: 12,
      labelWeight: "600",
      nodeProgramClasses: {
        "border-node": createNodeBorderProgram({
          borders: [
            { size: { value: 0.18 }, color: { attribute: "borderColor" } },
            { size: { fill: true }, color: { attribute: "color" } },
          ],
        }),
      },
    });
    sigmaRef.current = sigma;

    const animate = () => {
      const now = performance.now();
      const pulseState = pulseStateRef.current;
      const wId = winnerIdRef.current;
      let dirty = false;

      pulseState.forEach((startedAt, nodeId) => {
        const elapsed = now - startedAt;
        if (elapsed >= PULSE_DURATION_MS) {
          if (graph.hasNode(nodeId) && nodeId !== wId) {
            graph.setNodeAttribute(nodeId, "size", graph.getNodeAttribute(nodeId, "baseSize"));
          }
          pulseState.delete(nodeId);
          dirty = true;
          return;
        }
        if (graph.hasNode(nodeId) && nodeId !== wId) {
          const phase = elapsed / PULSE_DURATION_MS;
          const wave = Math.sin(phase * Math.PI);
          const baseSize = graph.getNodeAttribute(nodeId, "baseSize");
          graph.setNodeAttribute(nodeId, "size", baseSize * (1 + 0.5 * wave));
          dirty = true;
        }
      });

      if (wId && graph.hasNode(wId)) {
        const baseSize = graph.getNodeAttribute(wId, "baseSize");
        const phase = (now % 1500) / 1500;
        const wave = (Math.sin(phase * Math.PI * 2) + 1) / 2;
        graph.setNodeAttribute(wId, "size", baseSize * (1 + 0.4 * wave));
        dirty = true;
      }

      if (dirty) sigma.refresh();
      animationRef.current = requestAnimationFrame(animate);
    };
    animationRef.current = requestAnimationFrame(animate);

    return () => {
      if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
      sigma.kill();
      graph.clear();
      sigmaRef.current = null;
      graphRef.current = null;
    };
  }, []);

  useEffect(() => {
    const graph = graphRef.current;
    const sigma = sigmaRef.current;
    if (!graph || !sigma) return;

    const renderable = sampleAgents(agents, MAX_RENDERED_NODES);
    const renderableIds = new Set(renderable.map((agent) => agent.id));

    graph.forEachNode((nodeId) => {
      if (!renderableIds.has(nodeId)) graph.dropNode(nodeId);
    });

    const isFirstLayout = graph.order === 0;

    renderable.forEach((agent, index) => {
      const isWinner = agent.status === "winner";
      const tierBase = TIER_SIZES[agent.tier];
      const baseSize = isWinner ? tierBase * 1.6 : tierBase;
      const archetypeColor = ARCHETYPE_COLORS[agent.archetype] ?? "#888888";
      const color = isWinner ? WINNER_FILL : archetypeColor;
      const borderColor = isWinner
        ? WINNER_BORDER
        : agent.tier === "T1"
          ? "#f6f0e3"
          : agent.tier === "T2"
            ? "rgba(246, 240, 227, 0.45)"
            : archetypeColor;
      const label = isWinner ? `WINNER / ${agent.id}` : agent.id;
      const angle = index * 2.399963;
      const ring = Math.sqrt((index + 1) / Math.max(1, renderable.length));
      const fallbackX = Math.cos(angle) * ring * 50;
      const fallbackY = Math.sin(angle) * ring * 50;
      const nodeAttributes = {
        label,
        size: baseSize,
        baseSize,
        color,
        borderColor,
        type: "border-node",
        archetype: agent.archetype,
        tier: agent.tier,
        forceLabel: isWinner,
      };
      if (graph.hasNode(agent.id)) {
        graph.mergeNodeAttributes(agent.id, nodeAttributes);
      } else {
        graph.addNode(agent.id, {
          ...nodeAttributes,
          x: fallbackX,
          y: fallbackY,
        });
      }
    });

    if (isFirstLayout && graph.order > 0) {
      forceAtlas2.assign(graph, {
        iterations: 80,
        settings: { gravity: 1, scalingRatio: 2, slowDown: 3, barnesHutOptimize: graph.order > 200 },
      });
    }

    const edgesToKeep = new Set<string>();
    axlMessages.forEach((message) => {
      if (!graph.hasNode(message.source) || !graph.hasNode(message.target)) return;
      const age = tick - message.tick;
      if (age >= EDGE_DECAY_TICKS) return;
      const opacity = Math.max(0.1, 1 - age / EDGE_DECAY_TICKS);
      const edgeKey = `${message.source}->${message.target}`;
      edgesToKeep.add(edgeKey);
      const color = `rgba(157, 185, 165, ${opacity.toFixed(2)})`;
      if (graph.hasEdge(message.source, message.target)) {
        graph.mergeEdgeAttributes(message.source, message.target, { color, size: 1 });
      } else {
        graph.addEdgeWithKey(edgeKey, message.source, message.target, { color, size: 1 });
      }
    });

    graph.forEachEdge((edgeKey) => {
      if (!edgesToKeep.has(edgeKey)) graph.dropEdge(edgeKey);
    });

    const pulseState = pulseStateRef.current;
    const now = performance.now();
    const wId = winnerIdRef.current;
    axlMessages.forEach((message) => {
      if (tick - message.tick !== 0) return;
      [message.source, message.target].forEach((nodeId) => {
        if (graph.hasNode(nodeId) && nodeId !== wId) pulseState.set(nodeId, now);
      });
    });

    sigma.refresh();
  }, [agents, axlMessages, tick]);

  useEffect(() => {
    if (!winnerId || winnerId === previousWinnerIdRef.current) return;
    const sigma = sigmaRef.current;
    const graph = graphRef.current;
    if (!sigma || !graph || !graph.hasNode(winnerId)) return;
    previousWinnerIdRef.current = winnerId;
    try {
      const display = sigma.getNodeDisplayData(winnerId);
      if (!display) {
        previousWinnerIdRef.current = null;
        return;
      }
      sigma.getCamera().animate(
        { x: display.x, y: display.y, ratio: 0.55 },
        { duration: 800 },
      );
    } catch {
      // sigma may not be ready yet on first paint; the next agents update will retry
      previousWinnerIdRef.current = null;
    }
  }, [winnerId]);

  return <div className="sigma-canvas" ref={containerRef} />;
}

function GraphLegend() {
  const [open, setOpen] = useState(true);
  const archetypes = Object.keys(ARCHETYPE_LABELS) as Archetype[];

  return (
    <div className={`graph-legend ${open ? "open" : "closed"}`}>
      <button
        type="button"
        className="graph-legend-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span>Legend</span>
        <span className="graph-legend-chevron" aria-hidden>
          {open ? "-" : "+"}
        </span>
      </button>
      {open ? (
        <div className="graph-legend-body">
          <div className="graph-legend-section">
            <p className="graph-legend-eyebrow">Archetype</p>
            <div className="graph-legend-grid">
              {archetypes.map((arch) => (
                <span className="graph-legend-row" key={arch}>
                  <span
                    className="graph-legend-dot"
                    style={{ background: ARCHETYPE_COLORS[arch] }}
                  />
                  <span>{ARCHETYPE_LABELS[arch]}</span>
                </span>
              ))}
            </div>
          </div>
          <div className="graph-legend-section">
            <p className="graph-legend-eyebrow">Tier (size)</p>
            <div className="graph-legend-tiers">
              <span className="graph-legend-row">
                <span className="graph-legend-tier-dot tier-large" />
                <span>T1 - 0G AI</span>
              </span>
              <span className="graph-legend-row">
                <span className="graph-legend-tier-dot tier-medium" />
                <span>T2 - local rules</span>
              </span>
              <span className="graph-legend-row">
                <span className="graph-legend-tier-dot tier-small" />
                <span>T3 - idle</span>
              </span>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function SwarmGraph({
  agents,
  axlMessages,
  tick,
  totalAgentCount,
  totalAxlMessages,
}: {
  agents: SwarmAgent[];
  axlMessages: AxlEdgeMessage[];
  tick: number;
  totalAgentCount: number;
  totalAxlMessages: number;
}) {
  const [showConnecting, setShowConnecting] = useState(true);
  const [tickPulse, setTickPulse] = useState(false);
  const previousTickRef = useRef(tick);

  useEffect(() => {
    const handle = window.setTimeout(() => setShowConnecting(false), CONNECTING_OVERLAY_MS);
    return () => window.clearTimeout(handle);
  }, []);

  useEffect(() => {
    if (tick === previousTickRef.current) return;
    previousTickRef.current = tick;
    setTickPulse(true);
    const handle = window.setTimeout(() => setTickPulse(false), 220);
    return () => window.clearTimeout(handle);
  }, [tick]);

  const winnerId = useMemo(
    () => agents.find((agent) => agent.status === "winner")?.id ?? null,
    [agents],
  );

  const renderedCount = Math.min(agents.length, MAX_RENDERED_NODES);
  const trueCount = totalAgentCount || agents.length;
  const showOverlay = showConnecting && agents.length === 0;

  return (
    <section
      className={`panel graph-panel${tickPulse ? " tick-pulse" : ""}`}
      aria-labelledby="graph-heading"
    >
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Swarm execution</p>
          <h2 id="graph-heading">
            {agents.length === 0 ? "Awaiting swarm stream" : `${trueCount} agents reacting`}
          </h2>
        </div>
        <span className="tick" key={tick}>
          tick {tick}
        </span>
      </div>
      <div className="graph-stage">
        <SwarmGraphCanvas
          agents={agents}
          axlMessages={axlMessages}
          tick={tick}
          winnerId={winnerId}
        />
        <div className="axl-counter-badge" aria-live="polite">
          <span className="axl-counter-label">AXL msgs</span>
          <strong key={totalAxlMessages}>{totalAxlMessages.toLocaleString()}</strong>
          {trueCount > MAX_RENDERED_NODES ? (
            <span className="axl-counter-sub">
              rendering {renderedCount} / {trueCount}
            </span>
          ) : null}
        </div>
        <GraphLegend />
        {showOverlay ? (
          <div className="graph-connecting-overlay">
            <div className="graph-spinner" aria-hidden />
            <p>Connecting to swarm...</p>
          </div>
        ) : null}
      </div>
    </section>
  );
}
