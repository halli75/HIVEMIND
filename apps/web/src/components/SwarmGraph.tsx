import { useEffect, useMemo, useRef, useState } from "react";
import Graph from "graphology";
import Sigma from "sigma";
import forceAtlas2 from "graphology-layout-forceatlas2";
import FA2Layout from "graphology-layout-forceatlas2/worker";
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

export const ACTION_COLORS: Record<string, string> = {
  buy: "#00ffaa",
  sell: "#ff3355",
  arb: "#cc77ff",
  front_run: "#ffb800",
  rebalance: "#00bfff",
  provide_liquidity: "#00ff80",
  hedge: "#ff7700",
  vote: "#aa88ff",
  hold: "#4a6060",
};

export const ACTION_LABELS: Record<string, string> = {
  buy: "BUY",
  sell: "SELL",
  arb: "ARB",
  front_run: "FRONT-RUN",
  rebalance: "REBAL",
  provide_liquidity: "LP+",
  hedge: "HEDGE",
  vote: "VOTE",
  hold: "HOLD",
};

const DEFAULT_ACTION_COLOR = "#4a6060";

const TIER_SIZES = { T1: 13, T2: 8, T3: 5 } as const;

const WINNER_FILL = "#fff09a";
const WINNER_BORDER = "#ffe45c";
const SELECTED_BORDER = "#00ffaa";

const MAX_RENDERED_NODES = 500;
const PULSE_DURATION_MS = 480;
const EDGE_DECAY_TICKS = 4;
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
  onNodeClick,
  selectedNodeId,
  onBackgroundClick,
}: {
  agents: SwarmAgent[];
  axlMessages: AxlEdgeMessage[];
  tick: number;
  winnerId: string | null;
  onNodeClick?: (nodeId: string) => void;
  selectedNodeId?: string | null;
  onBackgroundClick?: () => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const layoutRef = useRef<InstanceType<typeof FA2Layout> | null>(null);
  const pulseStateRef = useRef<Map<string, number>>(new Map());
  const animationRef = useRef<number | null>(null);
  const winnerIdRef = useRef<string | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  const previousWinnerIdRef = useRef<string | null>(null);
  const onNodeClickRef = useRef<typeof onNodeClick>(onNodeClick);
  const onBackgroundClickRef = useRef<typeof onBackgroundClick>(onBackgroundClick);

  useEffect(() => {
    winnerIdRef.current = winnerId;
  }, [winnerId]);

  useEffect(() => {
    selectedIdRef.current = selectedNodeId ?? null;
  }, [selectedNodeId]);

  useEffect(() => {
    onNodeClickRef.current = onNodeClick;
  }, [onNodeClick]);

  useEffect(() => {
    onBackgroundClickRef.current = onBackgroundClick;
  }, [onBackgroundClick]);

  useEffect(() => {
    if (!containerRef.current) return;

    const graph = new Graph({ multi: false, type: "directed" });
    graphRef.current = graph;

    const sigma = new Sigma(graph, containerRef.current, {
      renderEdgeLabels: false,
      defaultEdgeColor: "rgba(0, 255, 170, 0.35)",
      labelColor: { color: "#a8ffd8" },
      labelSize: 11,
      labelWeight: "600",
      labelFont: "'Chakra Petch', monospace",
      nodeProgramClasses: {
        "border-node": createNodeBorderProgram({
          borders: [
            { size: { value: 0.22 }, color: { attribute: "borderColor" } },
            { size: { fill: true }, color: { attribute: "color" } },
          ],
        }),
      },
    });
    sigmaRef.current = sigma;

    sigma.on("clickNode", ({ node }) => {
      onNodeClickRef.current?.(node);
    });

    sigma.on("clickStage", () => {
      onBackgroundClickRef.current?.();
    });

    const animate = () => {
      const now = performance.now();
      const pulseState = pulseStateRef.current;
      const wId = winnerIdRef.current;
      const sId = selectedIdRef.current;
      let dirty = false;

      pulseState.forEach((startedAt, nodeId) => {
        const elapsed = now - startedAt;
        if (elapsed >= PULSE_DURATION_MS) {
          if (graph.hasNode(nodeId) && nodeId !== wId && nodeId !== sId) {
            graph.setNodeAttribute(nodeId, "size", graph.getNodeAttribute(nodeId, "baseSize"));
          }
          pulseState.delete(nodeId);
          dirty = true;
          return;
        }
        if (graph.hasNode(nodeId) && nodeId !== wId && nodeId !== sId) {
          const phase = elapsed / PULSE_DURATION_MS;
          const wave = Math.sin(phase * Math.PI);
          const baseSize = graph.getNodeAttribute(nodeId, "baseSize");
          graph.setNodeAttribute(nodeId, "size", baseSize * (1 + 0.6 * wave));
          dirty = true;
        }
      });

      if (wId && graph.hasNode(wId)) {
        const baseSize = graph.getNodeAttribute(wId, "baseSize");
        const phase = (now % 1500) / 1500;
        const wave = (Math.sin(phase * Math.PI * 2) + 1) / 2;
        graph.setNodeAttribute(wId, "size", baseSize * (1 + 0.45 * wave));
        dirty = true;
      }

      if (sId && sId !== wId && graph.hasNode(sId)) {
        const baseSize = graph.getNodeAttribute(sId, "baseSize");
        const phase = (now % 1100) / 1100;
        const wave = (Math.sin(phase * Math.PI * 2) + 1) / 2;
        graph.setNodeAttribute(sId, "size", baseSize * (1.7 + 0.25 * wave));
        dirty = true;
      }

      if (dirty) sigma.refresh();
      animationRef.current = requestAnimationFrame(animate);
    };
    animationRef.current = requestAnimationFrame(animate);

    return () => {
      if (animationRef.current !== null) cancelAnimationFrame(animationRef.current);
      if (layoutRef.current) {
        layoutRef.current.kill();
        layoutRef.current = null;
      }
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
      const action = agent.action ?? "hold";
      const actionColor = ACTION_COLORS[action] ?? DEFAULT_ACTION_COLOR;
      const color = isWinner ? WINNER_FILL : archetypeColor;
      const borderColor = isWinner
        ? WINNER_BORDER
        : agent.tier === "T1"
          ? actionColor
          : agent.tier === "T2"
            ? `${actionColor}aa`
            : archetypeColor;
      const label = isWinner ? `★ ${agent.id}` : agent.id;
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
        action,
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

      // Start continuous physics worker after seeding the layout once.
      if (!layoutRef.current) {
        const layout = new FA2Layout(graph, {
          settings: {
            gravity: 0.35,
            scalingRatio: 3,
            slowDown: 18,
            adjustSizes: false,
            barnesHutOptimize: graph.order > 200,
            strongGravityMode: false,
          },
        });
        layout.start();
        layoutRef.current = layout;
      }
    }

    const edgesToKeep = new Set<string>();
    axlMessages.forEach((message) => {
      if (!graph.hasNode(message.source) || !graph.hasNode(message.target)) return;
      const age = tick - message.tick;
      if (age >= EDGE_DECAY_TICKS) return;
      const opacity = Math.max(0.15, 1 - age / EDGE_DECAY_TICKS);
      const edgeKey = `${message.source}->${message.target}`;
      edgesToKeep.add(edgeKey);
      const color =
        age === 0
          ? `rgba(0, 255, 170, ${opacity.toFixed(2)})`
          : `rgba(120, 200, 180, ${opacity.toFixed(2)})`;
      const size = age === 0 ? 1.6 : 1;
      if (graph.hasEdge(message.source, message.target)) {
        graph.mergeEdgeAttributes(message.source, message.target, { color, size });
      } else {
        graph.addEdgeWithKey(edgeKey, message.source, message.target, { color, size });
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
    const graph = graphRef.current;
    const sigma = sigmaRef.current;
    if (!graph || !sigma) return;
    const wId = winnerIdRef.current;
    graph.forEachNode((nodeId) => {
      const base = graph.getNodeAttribute(nodeId, "baseSize");
      if (typeof base !== "number") return;
      if (nodeId === wId) return;
      if (nodeId === selectedNodeId) {
        graph.setNodeAttribute(nodeId, "borderColor", SELECTED_BORDER);
      } else {
        // Restore action-derived border using current node attributes.
        const tier = graph.getNodeAttribute(nodeId, "tier") as string | undefined;
        const action = (graph.getNodeAttribute(nodeId, "action") as string | undefined) ?? "hold";
        const archetype = graph.getNodeAttribute(nodeId, "archetype") as Archetype | undefined;
        const actionColor = ACTION_COLORS[action] ?? DEFAULT_ACTION_COLOR;
        const archetypeColor = (archetype && ARCHETYPE_COLORS[archetype]) || "#888888";
        const restored =
          tier === "T1"
            ? actionColor
            : tier === "T2"
              ? `${actionColor}aa`
              : archetypeColor;
        graph.setNodeAttribute(nodeId, "borderColor", restored);
        if (!pulseStateRef.current.has(nodeId)) {
          graph.setNodeAttribute(nodeId, "size", base);
        }
      }
    });
    sigma.refresh();
  }, [selectedNodeId]);

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
      previousWinnerIdRef.current = null;
    }
  }, [winnerId]);

  return <div className="sigma-canvas" ref={containerRef} />;
}

function GraphLegend() {
  const [open, setOpen] = useState(false);
  const archetypes = Object.keys(ARCHETYPE_LABELS) as Archetype[];
  const actionKeys = Object.keys(ACTION_LABELS);

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
          {open ? "−" : "+"}
        </span>
      </button>
      {open ? (
        <div className="graph-legend-body">
          <div className="graph-legend-section">
            <p className="graph-legend-eyebrow">Action / border</p>
            <div className="graph-legend-grid">
              {actionKeys.map((action) => (
                <span className="graph-legend-row" key={action}>
                  <span
                    className="graph-legend-dot"
                    style={{
                      background: "transparent",
                      border: `2px solid ${ACTION_COLORS[action]}`,
                      boxShadow: `0 0 8px ${ACTION_COLORS[action]}`,
                    }}
                  />
                  <span>{ACTION_LABELS[action]}</span>
                </span>
              ))}
            </div>
          </div>
          <div className="graph-legend-section">
            <p className="graph-legend-eyebrow">Archetype / fill</p>
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
  onNodeClick,
  selectedNodeId,
  onBackgroundClick,
}: {
  agents: SwarmAgent[];
  axlMessages: AxlEdgeMessage[];
  tick: number;
  totalAgentCount: number;
  totalAxlMessages: number;
  onNodeClick?: (nodeId: string) => void;
  selectedNodeId?: string | null;
  onBackgroundClick?: () => void;
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
    <div className={`graph-viewport-inner${tickPulse ? " tick-pulse" : ""}`}>
      <SwarmGraphCanvas
        agents={agents}
        axlMessages={axlMessages}
        tick={tick}
        winnerId={winnerId}
        onNodeClick={onNodeClick}
        selectedNodeId={selectedNodeId}
        onBackgroundClick={onBackgroundClick}
      />

      <div className="graph-overlay-top">
        <div className="graph-title-block">
          <span className="graph-title-line">SWARM // LIVE</span>
          <span className="graph-title-sub">
            {agents.length === 0
              ? "AWAITING TELEMETRY"
              : `${trueCount.toLocaleString()} AGENTS · TICK ${tick}`}
          </span>
        </div>
        <div className="graph-axl-counter" aria-live="polite">
          <span className="graph-axl-label">AXL MSGS</span>
          <strong key={totalAxlMessages}>{totalAxlMessages.toLocaleString()}</strong>
          {trueCount > MAX_RENDERED_NODES ? (
            <span className="graph-axl-sub">
              rendering {renderedCount} / {trueCount}
            </span>
          ) : null}
        </div>
      </div>

      <GraphLegend />

      {showOverlay ? (
        <div className="graph-connecting-overlay">
          <div className="graph-spinner" aria-hidden />
          <p>Establishing neural link...</p>
        </div>
      ) : null}
    </div>
  );
}
