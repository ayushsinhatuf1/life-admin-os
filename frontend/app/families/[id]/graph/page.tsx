"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";

interface GraphNode {
  id: string;
  type: "person" | "asset" | "property";
  label: string;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

interface GraphEdge {
  from: string;
  to: string;
  label: string;
  verification?: "verified" | "unverified";
}

const TYPE_CONFIG = {
  person: {
    label: "Person",
    color: "fill-blue-500 stroke-blue-600",
    bgColor: "bg-blue-50 text-blue-800 border-blue-200",
    nodeColor: "#3b82f6",
    shape: "circle",
    icon: "👤",
  },
  asset: {
    label: "Asset",
    color: "fill-emerald-500 stroke-emerald-600",
    bgColor: "bg-emerald-50 text-emerald-800 border-emerald-200",
    nodeColor: "#10b981",
    shape: "diamond",
    icon: "💼",
  },
  property: {
    label: "Property",
    color: "fill-amber-500 stroke-amber-600",
    bgColor: "bg-amber-50 text-amber-800 border-amber-200",
    nodeColor: "#f59e0b",
    shape: "rect",
    icon: "🏡",
  },
};

export default function FamilyGraphPage() {
  const params = useParams();
  const familyId = params?.id as string;

  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [filterType, setFilterType] = useState<string>("all");
  const [isMobile, setIsMobile] = useState(false);

  const svgRef = useRef<SVGSVGElement>(null);
  const animFrameRef = useRef<number | null>(null);

  // Check window width for mobile list view fallback
  useEffect(() => {
    function checkMobile() {
      setIsMobile(window.innerWidth < 768);
    }
    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, []);

  // Fetch Graph data from API
  useEffect(() => {
    if (!familyId) return;

    async function loadGraph() {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getGraph(familyId);
        setNodes(data.nodes);
        setEdges(data.edges);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load knowledge graph.");
      } finally {
        setLoading(false);
      }
    }

    loadGraph();
  }, [familyId]);

  // Force simulation logic (physics layout without external heavy bundles)
  useEffect(() => {
    if (nodes.length === 0 || isMobile) return;

    const width = 800;
    const height = 550;
    const k = Math.sqrt((width * height) / Math.max(1, nodes.length));

    // Initialize positions if needed
    const simNodes = nodes.map((n, i) => ({
      ...n,
      x: n.x ?? width / 2 + (Math.cos(i) * 180 * (i + 1)) / (nodes.length + 1),
      y: n.y ?? height / 2 + (Math.sin(i) * 180 * (i + 1)) / (nodes.length + 1),
      vx: 0,
      vy: 0,
    }));

    const nodeMap = new Map(simNodes.map((n) => [n.id, n]));

    let iteration = 0;
    const maxIterations = 180;

    function step() {
      if (iteration >= maxIterations) return;
      iteration++;

      const cooling = 1 - iteration / maxIterations;

      // 1. Repulsion between all nodes
      for (let i = 0; i < simNodes.length; i++) {
        for (let j = i + 1; j < simNodes.length; j++) {
          const a = simNodes[i];
          const b = simNodes[j];
          const dx = (b.x ?? 0) - (a.x ?? 0);
          const dy = (b.y ?? 0) - (a.y ?? 0);
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = ((k * k) / dist) * 0.15;
          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;
          a.vx = (a.vx ?? 0) - fx;
          a.vy = (a.vy ?? 0) - fy;
          b.vx = (b.vx ?? 0) + fx;
          b.vy = (b.vy ?? 0) + fy;
        }
      }

      // 2. Attraction along edges
      for (const e of edges) {
        const source = nodeMap.get(e.from);
        const target = nodeMap.get(e.to);
        if (!source || !target) continue;

        const dx = (target.x ?? 0) - (source.x ?? 0);
        const dy = (target.y ?? 0) - (source.y ?? 0);
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (dist * dist) / (k * 1.5);
        const fx = (dx / dist) * force * 0.08;
        const fy = (dy / dist) * force * 0.08;
        source.vx = (source.vx ?? 0) + fx;
        source.vy = (source.vy ?? 0) + fy;
        target.vx = (target.vx ?? 0) - fx;
        target.vy = (target.vy ?? 0) - fy;
      }

      // 3. Centering force & velocity damping
      for (const n of simNodes) {
        const cx = width / 2 - (n.x ?? 0);
        const cy = height / 2 - (n.y ?? 0);
        n.vx = ((n.vx ?? 0) + cx * 0.01) * 0.75 * cooling;
        n.vy = ((n.vy ?? 0) + cy * 0.01) * 0.75 * cooling;

        n.x = Math.max(40, Math.min(width - 40, (n.x ?? 0) + (n.vx ?? 0)));
        n.y = Math.max(40, Math.min(height - 40, (n.y ?? 0) + (n.vy ?? 0)));
      }

      setNodes([...simNodes]);
      animFrameRef.current = requestAnimationFrame(step);
    }

    step();

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [edges.length, isMobile]);

  // Connected edges for the selected node
  const selectedNodeEdges = selectedNode
    ? edges.filter((e) => e.from === selectedNode.id || e.to === selectedNode.id)
    : [];

  const filteredNodes = filterType === "all" ? nodes : nodes.filter((n) => n.type === filterType);
  const nodeLookup = new Map(nodes.map((n) => [n.id, n]));

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="flex items-center gap-3 text-stone-500">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-stone-400 border-t-stone-800" />
          <span className="text-sm">Building family graph…</span>
        </div>
      </div>
    );
  }

  return (
    <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-stone-200 pb-4">
        <div>
          <span className="rounded bg-stone-100 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-stone-600">
            Family Knowledge Graph
          </span>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-stone-900">
            People, Assets & Properties
          </h1>
          <p className="mt-1 text-sm text-stone-500">
            Associations and ownership links across family records.
          </p>
        </div>

        {/* Filter controls */}
        <div className="flex items-center gap-2">
          {["all", "person", "property", "asset"].map((t) => (
            <button
              key={t}
              onClick={() => setFilterType(t)}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium capitalize transition ${
                filterType === t
                  ? "bg-stone-900 text-white shadow"
                  : "border border-stone-200 bg-white text-stone-600 hover:bg-stone-50"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Legend & Explanations */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-stone-200 bg-white p-3.5 text-xs text-stone-600 shadow-sm">
        <div className="flex flex-wrap items-center gap-4">
          <span className="font-semibold text-stone-900">Node Types:</span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-full bg-blue-500" /> Person
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-3 w-3 rounded bg-amber-500" /> Property
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-3 w-3 rotate-45 rounded-sm bg-emerald-500" /> Asset
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-4 border-t border-stone-100 pt-2 sm:border-t-0 sm:pt-0">
          <span className="font-semibold text-stone-900">Edge Provenance:</span>
          <span className="inline-flex items-center gap-2">
            <span className="h-0.5 w-6 bg-stone-700" /> Verified Link
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="h-0.5 w-6 border-b-2 border-dashed border-stone-400" /> Unverified Link (family-reported)
          </span>
        </div>
      </div>

      {/* Mobile view fallback: Degrades to responsive list */}
      {isMobile ? (
        <div className="space-y-4">
          <p className="rounded-lg bg-stone-100 p-3 text-xs text-stone-600">
            📱 Interactive graph view is optimized for desktop. Showing comprehensive family registry list below.
          </p>

          <ul className="divide-y divide-stone-200 rounded-xl border border-stone-200 bg-white shadow-sm">
            {filteredNodes.map((n) => {
              const cfg = TYPE_CONFIG[n.type];
              const connected = edges.filter((e) => e.from === n.id || e.to === n.id);

              return (
                <li
                  key={n.id}
                  onClick={() => setSelectedNode(n)}
                  className="cursor-pointer p-4 transition hover:bg-stone-50"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-xl">{cfg.icon}</span>
                      <div>
                        <h3 className="font-semibold text-stone-900">{n.label}</h3>
                        <span className={`inline-block rounded-full border px-2 py-0.5 text-[11px] ${cfg.bgColor}`}>
                          {cfg.label}
                        </span>
                      </div>
                    </div>
                    <span className="text-xs text-stone-400">
                      {connected.length} {connected.length === 1 ? "link" : "links"} →
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        /* Desktop: SVG Force Layout + Detail Side Panel */
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          <div className="relative min-h-[560px] overflow-hidden rounded-xl border border-stone-200 bg-stone-50/70 shadow-inner lg:col-span-8">
            <svg
              ref={svgRef}
              viewBox="0 0 800 550"
              className="h-full w-full select-none"
            >
              {/* Edges */}
              <g className="edges">
                {edges.map((edge, i) => {
                  const s = nodeLookup.get(edge.from);
                  const t = nodeLookup.get(edge.to);
                  if (!s || !t) return null;

                  const isUnverified = edge.verification === "unverified";
                  const isSelected =
                    selectedNode && (s.id === selectedNode.id || t.id === selectedNode.id);

                  const midX = ((s.x ?? 0) + (t.x ?? 0)) / 2;
                  const midY = ((s.y ?? 0) + (t.y ?? 0)) / 2;

                  return (
                    <g key={i}>
                      <line
                        x1={s.x ?? 0}
                        y1={s.y ?? 0}
                        x2={t.x ?? 0}
                        y2={t.y ?? 0}
                        stroke={isSelected ? "#1c1917" : isUnverified ? "#a8a29e" : "#57534e"}
                        strokeWidth={isSelected ? 2.5 : 1.5}
                        strokeDasharray={isUnverified ? "4,4" : undefined}
                      />
                      {edge.label && (
                        <text
                          x={midX}
                          y={midY - 4}
                          textAnchor="middle"
                          className="fill-stone-500 text-[10px] font-medium select-none pointer-events-none"
                        >
                          {edge.label}
                        </text>
                      )}
                    </g>
                  );
                })}
              </g>

              {/* Nodes */}
              <g className="nodes">
                {filteredNodes.map((n) => {
                  const isSelected = selectedNode?.id === n.id;
                  const cfg = TYPE_CONFIG[n.type];

                  return (
                    <g
                      key={n.id}
                      transform={`translate(${n.x ?? 400}, ${n.y ?? 275})`}
                      onClick={() => setSelectedNode(n)}
                      className="cursor-pointer transition-transform hover:scale-110"
                    >
                      {/* Node Shape */}
                      {n.type === "person" && (
                        <circle
                          r={20}
                          fill={cfg.nodeColor}
                          stroke={isSelected ? "#1c1917" : "#ffffff"}
                          strokeWidth={isSelected ? 3 : 2}
                          className="shadow-sm"
                        />
                      )}
                      {n.type === "property" && (
                        <rect
                          x={-18}
                          y={-18}
                          width={36}
                          height={36}
                          rx={6}
                          fill={cfg.nodeColor}
                          stroke={isSelected ? "#1c1917" : "#ffffff"}
                          strokeWidth={isSelected ? 3 : 2}
                        />
                      )}
                      {n.type === "asset" && (
                        <rect
                          x={-16}
                          y={-16}
                          width={32}
                          height={32}
                          rx={4}
                          transform="rotate(45)"
                          fill={cfg.nodeColor}
                          stroke={isSelected ? "#1c1917" : "#ffffff"}
                          strokeWidth={isSelected ? 3 : 2}
                        />
                      )}

                      {/* Icon */}
                      <text
                        textAnchor="middle"
                        dominantBaseline="central"
                        className="select-none pointer-events-none text-xs"
                      >
                        {cfg.icon}
                      </text>

                      {/* Label under node */}
                      <text
                        y={28}
                        textAnchor="middle"
                        className={`select-none pointer-events-none text-[11px] font-semibold ${
                          isSelected ? "fill-stone-900 font-bold" : "fill-stone-700"
                        }`}
                      >
                        {n.label.length > 16 ? `${n.label.slice(0, 14)}…` : n.label}
                      </text>
                    </g>
                  );
                })}
              </g>
            </svg>
          </div>

          {/* Right Side Panel: Records and linked documents */}
          <aside className="rounded-xl border border-stone-200 bg-white p-5 shadow-sm lg:col-span-4">
            {selectedNode ? (
              <div>
                <div className="flex items-center justify-between border-b border-stone-200 pb-3">
                  <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TYPE_CONFIG[selectedNode.type].bgColor}`}>
                    {TYPE_CONFIG[selectedNode.type].label}
                  </span>
                  <button
                    onClick={() => setSelectedNode(null)}
                    className="text-xs text-stone-400 hover:text-stone-700"
                  >
                    ✕ Close
                  </button>
                </div>

                <h3 className="mt-3 text-lg font-bold text-stone-900">
                  {selectedNode.label}
                </h3>
                <p className="mt-0.5 text-xs text-stone-500 font-mono">
                  ID: {selectedNode.id}
                </p>

                {/* Connected Relationships */}
                <div className="mt-5">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                    Connected Relationships ({selectedNodeEdges.length})
                  </h4>

                  {selectedNodeEdges.length === 0 ? (
                    <p className="mt-2 text-xs text-stone-400">
                      No direct associations linked to this record yet.
                    </p>
                  ) : (
                    <ul className="mt-2.5 space-y-2">
                      {selectedNodeEdges.map((edge, idx) => {
                        const otherId = edge.from === selectedNode.id ? edge.to : edge.from;
                        const otherNode = nodeLookup.get(otherId);
                        const isVerified = edge.verification === "verified";

                        return (
                          <li
                            key={idx}
                            onClick={() => otherNode && setSelectedNode(otherNode)}
                            className="cursor-pointer rounded-lg border border-stone-200 p-2.5 text-xs transition hover:bg-stone-50"
                          >
                            <div className="flex items-center justify-between">
                              <span className="font-medium text-stone-900">
                                {otherNode?.label ?? "Linked Record"}
                              </span>
                              <span className="text-[10px] text-stone-500 font-mono">
                                {otherNode ? TYPE_CONFIG[otherNode.type].label : "Entity"}
                              </span>
                            </div>
                            <div className="mt-1 flex items-center justify-between text-[11px] text-stone-500">
                              <span>Relationship: {edge.label}</span>
                              <span className={`font-semibold ${isVerified ? "text-emerald-700" : "text-amber-700"}`}>
                                {isVerified ? "✓ Verified" : "⚠ Unverified"}
                              </span>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>

                {/* Action Links */}
                <div className="mt-6 border-t border-stone-200 pt-4 flex flex-col gap-2">
                  <a
                    href={`/families/${familyId}/vault`}
                    className="rounded-lg bg-stone-900 px-4 py-2 text-center text-xs font-semibold text-white hover:bg-stone-800"
                  >
                    View in Vault
                  </a>
                </div>
              </div>
            ) : (
              <div className="flex h-64 flex-col items-center justify-center text-center text-stone-400">
                <span className="text-3xl">🕸</span>
                <p className="mt-2 text-sm font-medium text-stone-600">Select any node</p>
                <p className="mt-1 text-xs text-stone-400">
                  Click a person, property or asset to inspect verified ownership records and linked documents.
                </p>
              </div>
            )}
          </aside>
        </div>
      )}
    </main>
  );
}
