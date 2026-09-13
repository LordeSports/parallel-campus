/** [加分] 关系图（spec/07 §3.6）：d3-force，中心我的分身。 */

import { useEffect, useMemo, useRef } from 'react';
import {
  forceCenter,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force';

import type { ReportFriendView } from '../api/types';

interface Node extends SimulationNodeDatum {
  id: string;
  name: string;
  kind: 'me' | 'player' | 'npc' | 'system';
  r: number;
}

type Link = SimulationLinkDatum<Node>;

const W = 560;
const H = 320;

export default function RelationGraph({ friends }: { friends: ReportFriendView[] }) {
  const edges = useMemo(() => friends.filter((f) => f.affinity > 10), [friends]);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const nodes = useMemo<Node[]>(() => {
    const center: Node = { id: '__me__', name: '我', kind: 'me', r: 18, x: W / 2, y: H / 2 };
    const others: Node[] = edges.map((f) => ({
      id: f.character.id,
      name: f.character.name,
      kind: f.character.kind === 'npc' ? 'npc' : 'player',
      r: 12,
    }));
    return [center, ...others];
  }, [edges]);

  const links = useMemo<Link[]>(
    () => edges.map((f) => ({ source: '__me__', target: f.character.id, value: f.affinity } as unknown as Link)),
    [edges],
  );

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || edges.length === 0) return;

    const sim = forceSimulation<Node>(nodes)
      .force('charge', forceManyBody().strength(-260))
      .force('center', forceCenter(W / 2, H / 2))
      .force(
        'link',
        forceLink<Node, Link>(links)
          .id((d) => d.id)
          .distance((l) => 130 - Math.min(60, (l as { value?: number }).value ?? 0))
          .strength(0.6),
      );

    const g = svg.querySelector('g');
    const tick = () => {
      if (!g) return;
      const byId = new Map(nodes.map((n) => [n.id, n]));
      for (const l of links) {
        const s = typeof l.source === 'string' ? byId.get(l.source) : (l.source as Node);
        const t = typeof l.target === 'string' ? byId.get(l.target) : (l.target as Node);
        const el = g.querySelector<SVGLineElement>(`[data-link="${(l as { index?: number }).index}"]`);
        if (el && s && t) {
          el.setAttribute('x1', String(s.x ?? 0));
          el.setAttribute('y1', String(s.y ?? 0));
          el.setAttribute('x2', String(t.x ?? 0));
          el.setAttribute('y2', String(t.y ?? 0));
        }
      }
      for (const n of nodes) {
        const el = g.querySelector<SVGGElement>(`[data-node="${n.id}"]`);
        if (el) el.setAttribute('transform', `translate(${n.x ?? 0} ${n.y ?? 0})`);
      }
    };

    sim.on('tick', tick);
    return () => {
      sim.stop();
    };
  }, [nodes, links, edges.length]);

  if (edges.length === 0) return null;

  return (
    <section className="card p-4">
      <h2 className="mb-2 text-sm font-medium text-ink">关系网</h2>
      <p className="mb-2 text-xs text-muted">线越粗，你们越熟</p>
      <div className="overflow-hidden rounded-xl bg-paper">
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="h-64 w-full">
          <g>
            {links.map((l, i) => (
              <line
                key={i}
                data-link={i}
                stroke="#0084ff"
                strokeOpacity="0.35"
                strokeWidth={Math.max(1, Math.min(6, ((l as { value?: number }).value ?? 0) / 8))}
              />
            ))}
            {nodes.map((n) => (
              <g key={n.id} data-node={n.id}>
                <circle
                  r={n.r}
                  fill={n.kind === 'me' ? '#f59e0b' : n.kind === 'npc' ? '#94a3b8' : '#0084ff'}
                  stroke="#ffffff"
                  strokeWidth="2"
                />
                <text
                  textAnchor="middle"
                  dy={n.r + 12}
                  fontSize="10"
                  fill="#4b5563"
                >
                  {n.name.length > 6 ? `${n.name.slice(0, 6)}…` : n.name}
                </text>
              </g>
            ))}
          </g>
        </svg>
      </div>
    </section>
  );
}
