import { useEffect, useMemo, useRef } from "react";
import Graph from "graphology";
import Sigma from "sigma";
import forceAtlas2 from "graphology-layout-forceatlas2";
import { createNodeBorderProgram } from "@sigma/node-border";
import type { Archetype, AxlEdgeMessage, SwarmAgent } from "../types";

const ARCHETYPE_COLORS: Record<Archetype, string> = {
  whale: "#3B82F6",
  degen: "#F59E0B",
  lp_provider: "#10B981",
  arbitrageur: "#8B5CF6",
  governance_voter: "#6B7280",
  stablecoin_arb: "#06B6D4",
  mev_searcher: "#EF4444",
};

const TIER_SIZES = { T1: 12, T2: 8, T3: 5 } as const;
const PLACEHOLDER_DISTRIBUTION: { archetype: Archetype; count: number }[] = [
  { archetype: "degen", count: 6 },
  { archetype: "whale", count: 4 },
  { archetype: "lp_provider", count: 3 },
  { archetype: "arbitrageur", count: 3 },
  { archetype: "mev_searcher", count: 2 },
  { archetype: "governance_voter", count: 1 },
  { archetype: "stablecoin_arb", count: 1 },
];

const MAX_RENDERED_NODES = 500;
const PULSE_DURATION_MS = 400;
const EDGE_DECAY_TICKS = 3;

const buildPlaceholderAgents = (): SwarmAgent[] => {
  const out: SwarmAgent[] = [];
  let index = 0;
  for (const entry of PLACEHOLDER_DISTRIBUTION) {
    for (let i = 0; i < entry.count; i += 1) {
      const angle = index * 2.399963;
      const ring = Math.sqrt((index + 1) / 20);
      const tier = index % 11 === 0 ? "T1" : index % 4 === 0 ? "T2" : "T3";
      out.push({
        id: `placeholder-${index}`,
        x: 50 + Math.cos(angle) * ring * 46,
        y: 50 + Math.sin(angle) * ring * 42,
        tier,
        status: "queued",
        score: 50,
        confidence: 0.5,
        strategy: `${entry.archetype} / hold`,
        archetype: entry.archetype,
      });
      index += 1;
    }
  }
  return out;
};

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
}: {
  agents: SwarmAgent[];
  axlMessages: AxlEdgeMessage[];
  tick: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const pulseStateRef = useRef<Map<string, number>>(new Map());
  const animationRef = useRef<number | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const graph = new Graph({ multi: false, type: "directed" });
    graphRef.current = graph;

    const sigma = new Sigma(graph, containerRef.current, {
      renderEdgeLabels: false,
      defaultEdgeColor: "rgba(157, 185, 165, 0.35)",
      labelColor: { color: "#cfc7b8" },
      labelSize: 11,
      nodeProgramClasses: {
        "border-node": createNodeBorderProgram({
          borders: [
            { size: { value: 0.15 }, color: { attribute: "borderColor" } },
            { size: { fill: true }, color: { attribute: "color" } },
          ],
        }),
      },
    });
    sigmaRef.current = sigma;

    const animate = () => {
      const now = performance.now();
      const pulseState = pulseStateRef.current;
      let dirty = false;
      pulseState.forEach((startedAt, nodeId) => {
        const elapsed = now - startedAt;
        if (elapsed >= PULSE_DURATION_MS) {
          if (graph.hasNode(nodeId)) {
            graph.setNodeAttribute(nodeId, "size", graph.getNodeAttribute(nodeId, "baseSize"));
          }
          pulseState.delete(nodeId);
          dirty = true;
          return;
        }
        const phase = elapsed / PULSE_DURATION_MS;
        const wave = Math.sin(phase * Math.PI);
        const baseSize = graph.hasNode(nodeId) ? graph.getNodeAttribute(nodeId, "baseSize") : 0;
        if (graph.hasNode(nodeId)) {
          graph.setNodeAttribute(nodeId, "size", baseSize * (1 + 0.5 * wave));
          dirty = true;
        }
      });
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
      const baseSize = TIER_SIZES[agent.tier];
      const color = ARCHETYPE_COLORS[agent.archetype] ?? "#888888";
      const borderColor =
        agent.tier === "T1" ? "#f6f0e3" : agent.tier === "T2" ? "rgba(246, 240, 227, 0.45)" : color;
      const angle = index * 2.399963;
      const ring = Math.sqrt((index + 1) / Math.max(1, renderable.length));
      const fallbackX = Math.cos(angle) * ring * 50;
      const fallbackY = Math.sin(angle) * ring * 50;
      const nodeAttributes = {
        label: agent.id,
        size: baseSize,
        baseSize,
        color,
        borderColor,
        type: "border-node",
        archetype: agent.archetype,
        tier: agent.tier,
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
    axlMessages.forEach((message) => {
      if (tick - message.tick !== 0) return;
      [message.source, message.target].forEach((nodeId) => {
        if (graph.hasNode(nodeId)) pulseState.set(nodeId, now);
      });
    });

    sigma.refresh();
  }, [agents, axlMessages, tick]);

  return <div className="sigma-canvas" ref={containerRef} />;
}

export function SwarmGraph({
  agents,
  axlMessages,
  tick,
  totalAgentCount,
  totalAxlMessages,
  loading = false,
}: {
  agents: SwarmAgent[];
  axlMessages: AxlEdgeMessage[];
  tick: number;
  totalAgentCount: number;
  totalAxlMessages: number;
  loading?: boolean;
}) {
  const isLoading = loading || agents.length === 0;
  const placeholderAgents = useMemo(() => buildPlaceholderAgents(), []);
  const visibleAgents = isLoading ? placeholderAgents : agents;
  const renderedCount = Math.min(visibleAgents.length, MAX_RENDERED_NODES);
  const trueCount = isLoading ? 0 : totalAgentCount || agents.length;

  return (
    <section className="panel graph-panel" aria-labelledby="graph-heading">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Swarm execution</p>
          <h2 id="graph-heading">
            {isLoading ? "Awaiting swarm stream" : `${trueCount} agents reacting`}
          </h2>
        </div>
        <span className="tick">tick {tick}</span>
      </div>
      <div className="graph-stage">
        <SwarmGraphCanvas
          agents={visibleAgents}
          axlMessages={isLoading ? [] : axlMessages}
          tick={tick}
        />
        <div className="axl-counter-badge" aria-live="polite">
          <span className="axl-counter-label">AXL msgs</span>
          <strong>{totalAxlMessages.toLocaleString()}</strong>
          {trueCount > MAX_RENDERED_NODES ? (
            <span className="axl-counter-sub">rendering {renderedCount} / {trueCount}</span>
          ) : null}
        </div>
        {isLoading ? (
          <div className="graph-loading-overlay">
            <span className="loading-pulse" />
            <span>Waiting for WebSocket data...</span>
          </div>
        ) : null}
      </div>
    </section>
  );
}
