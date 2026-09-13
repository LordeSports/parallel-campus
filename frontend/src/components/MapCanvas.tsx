/** SVG 校园地图（spec/07 §3.3）。
 *
 * 坐标直接取 `/api/world/locations` 的 x/y/w/h（后端已按 1000×600 画布布局）。
 */

import { useMemo, useState } from 'react';

import type { CharacterSummaryView, LocationView } from '../api/types';
import { moodEmoji, useWorld } from '../store/world';

const VIEW_W = 1000;
const VIEW_H = 600;
const PER_ROW = 5;
const GAP = 36;

export interface MapCanvasProps {
  onPickCharacter: (id: string) => void;
}

/** 地点内角色网格排布：返回第 i 个角色的坐标。 */
function occupantPos(loc: LocationView, total: number, i: number) {
  const cols = Math.min(PER_ROW, Math.max(1, total));
  const rows = Math.ceil(total / PER_ROW);
  const startX = loc.x + loc.w / 2 - ((cols - 1) * GAP) / 2;
  const startY = loc.y + loc.h / 2 - ((rows - 1) * GAP) / 2 + 8;
  return {
    x: startX + (i % PER_ROW) * GAP,
    y: startY + Math.floor(i / PER_ROW) * GAP,
  };
}

function CharacterDot({
  c,
  x,
  y,
  onPick,
}: {
  c: CharacterSummaryView;
  x: number;
  y: number;
  onPick: (id: string) => void;
}) {
  const r = c.kind === 'player' ? 18 : 16;
  const stroke = c.is_me ? '#f59e0b' : c.kind === 'player' ? '#0084ff' : '#94a3b8';
  const face = c.kind === 'system' ? '📢' : moodEmoji(c.mood?.valence, c.mood?.arousal);

  return (
    <g
      className="map-character"
      transform={`translate(${x} ${y})`}
      opacity={c.is_asleep ? 0.6 : 1}
      onClick={() => onPick(c.id)}
      style={{ cursor: 'pointer' }}
    >
      <circle r={r} fill="#ffffff" stroke={stroke} strokeWidth={c.is_me ? 3 : 2} />
      {(c.is_me || c.kind === 'player') && !c.is_asleep && c.activity && (
        <g className="agent-bubble" transform={`translate(22 ${-r - 8})`}>
          <rect width={Math.min(150, Math.max(70, c.activity.length * 12))} height="22" rx="11" fill="#ffffff" stroke="#dbeafe" />
          <text x="10" y="15" fontSize="10" fill="#2563eb">{c.activity.slice(0, 12)}</text>
        </g>
      )}
      <text textAnchor="middle" dy="5" fontSize="14" style={{ pointerEvents: 'none' }}>
        {face}
      </text>
      <text
        textAnchor="middle"
        dy={r + 12}
        fontSize="10"
        fill="#4b5563"
        style={{ pointerEvents: 'none' }}
      >
        {c.name.length > 6 ? `${c.name.slice(0, 6)}…` : c.name}
        {c.is_me ? ' ·我' : ''}
      </text>
      {c.is_asleep && (
        <text x={r - 2} y={-r + 4} fontSize="11" style={{ pointerEvents: 'none' }}>
          💤
        </text>
      )}
    </g>
  );
}

export default function MapCanvas({ onPickCharacter }: MapCanvasProps) {
  const locations = useWorld((s) => s.locations);
  const characters = useWorld((s) => s.characters);
  const state = useWorld((s) => s.state);
  const dialogues = useWorld((s) => s.dialogues);
  const [hover, setHover] = useState<string | null>(null);

  const rainy = state?.weather?.kind === 'rainy';
  const activeIds = useMemo(
    () => new Set((state?.active_events ?? []).map((e) => e.location_id).filter(Boolean)),
    [state?.active_events],
  );

  /** 地点 → 在场角色。角色状态是唯一事实来源，避免 occupants 快照过期造成重复显示。 */
  const byLocation = useMemo(() => {
    const map = new Map<string, CharacterSummaryView[]>();
    for (const loc of locations) {
      const seen = new Set<string>();
      const current = Object.values(characters).filter(
        (c) => c.location_id === loc.id && !seen.has(c.id) && seen.add(c.id),
      );
      map.set(loc.id, current);
    }
    return map;
  }, [locations, characters]);

  /** 每角色在地图上的坐标（用于对话连线）。 */
  const positions = useMemo(() => {
    const pos = new Map<string, { x: number; y: number }>();
    for (const loc of locations) {
      const occ = byLocation.get(loc.id) ?? [];
      occ.forEach((c, i) => pos.set(c.id, occupantPos(loc, occ.length, i)));
    }
    return pos;
  }, [locations, byLocation]);

  /** 进行中的对话：两点之间画虚线。 */
  const dialogueLines = useMemo(() => {
    const lines: { key: string; x1: number; y1: number; x2: number; y2: number }[] = [];
    for (const d of Object.values(dialogues)) {
      if (d.ended) continue;
      const a = positions.get(d.aId);
      const b = positions.get(d.bId);
      if (a && b) lines.push({ key: d.id, x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    }
    return lines;
  }, [dialogues, positions]);

  return (
    <div className="relative h-full w-full overflow-hidden">
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full"
      >
        <defs>
          <linearGradient id="campus-sky" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#eaf3ff" />
            <stop offset="0.52" stopColor="#f7fbf2" />
            <stop offset="1" stopColor="#fff8ec" />
          </linearGradient>
          <filter id="map-shadow" x="-20%" y="-20%" width="140%" height="150%">
            <feDropShadow dx="0" dy="8" stdDeviation="8" floodColor="#94a3b8" floodOpacity=".18" />
          </filter>
          <filter id="event-glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="7" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="url(#campus-sky)" />
        <path d="M0 222 C190 188 290 258 440 218 S720 178 1000 230 L1000 390 C780 344 600 402 430 370 S160 344 0 390Z" fill="#dff2dc" opacity=".72" />
        <path d="M0 420 C220 390 320 460 510 424 S820 390 1000 430 L1000 600 0 600Z" fill="#f3ead6" opacity=".42" />
        <path d="M130 600 C210 470 280 350 460 280 S720 208 900 54" fill="none" stroke="#ffffff" strokeWidth="26" opacity=".7" strokeLinecap="round" />
        <path d="M80 160 C270 250 370 360 540 420 S760 490 940 535" fill="none" stroke="#ffffff" strokeWidth="18" opacity=".56" strokeLinecap="round" />
        <path d="M690 280 C770 250 900 260 965 310 C940 380 800 410 710 360Z" fill="#bde9ef" opacity=".82" />
        <path d="M720 300 C795 286 880 300 934 330" fill="none" stroke="#fff" strokeWidth="5" opacity=".55" strokeLinecap="round" />
        {[{x:30,y:222},{x:350,y:218},{x:675,y:208},{x:955,y:205},{x:450,y:452},{x:900,y:450}].map((tree) => (
          <g key={`${tree.x}-${tree.y}`} className="map-tree" transform={`translate(${tree.x} ${tree.y})`}>
            <circle r="18" fill="#9ed7a0" opacity=".9" /><circle cx="12" cy="4" r="12" fill="#83c98c" opacity=".9" /><rect x="-3" y="13" width="6" height="16" rx="3" fill="#b9825b" />
          </g>
        ))}
        {[...Array(20)].map((_, i) => (
          <circle
            key={i}
            cx={(i * 137) % VIEW_W}
            cy={((i * 211) % (VIEW_H - 40)) + 20}
            r={26}
            fill="#e3efe0"
            opacity={0.55}
          />
        ))}

        {/* 地点 */}
        {locations.map((loc) => {
          const occ = byLocation.get(loc.id) ?? [];
          const isHover = hover === loc.id;
          const isActive = activeIds.has(loc.id);
          const eventsHere = (state?.active_events ?? []).filter((event) => event.location_id === loc.id);
          return (
            <g
              key={loc.id}
              onMouseEnter={() => setHover(loc.id)}
              onMouseLeave={() => setHover(null)}
            >
              <rect
                x={loc.x}
                y={loc.y}
                width={loc.w}
                height={loc.h}
                rx={16}
                fill="#fbfdff"
                stroke={isActive ? '#0084ff' : '#dbe3ea'}
                strokeWidth={isActive ? 2.5 : 1.5}
                filter="url(#map-shadow)"
                className={isActive ? 'animate-pulse-ring map-location' : 'map-location'}
              />
              <text x={loc.x + 12} y={loc.y + 24} fontSize="18">
                {loc.emoji}
              </text>
              <text x={loc.x + 36} y={loc.y + 24} fontSize="13" fill="#374151">
                {loc.name}
              </text>
              <text
                x={loc.x + loc.w - 12}
                y={loc.y + 24}
                fontSize="11"
                fill="#6b7280"
                textAnchor="end"
              >
                {occ.length}/{loc.capacity}
              </text>

              {eventsHere.slice(0, 2).map((event, index) => (
                <g key={event.id} transform={`translate(${loc.x + loc.w - 28 - index * 24} ${loc.y + loc.h - 24})`} filter="url(#event-glow)" className="map-event-marker">
                  <circle r="12" fill="#fff7ed" stroke="#fb923c" strokeWidth="1.5" />
                  <text textAnchor="middle" dy="5" fontSize="12">{index === 0 ? '✦' : '!'}</text>
                </g>
              ))}

              {/* 雨纹（室外） */}
              {rainy &&
                loc.outdoor &&
                [...Array(8)].map((_, i) => (
                  <line
                    key={i}
                    x1={loc.x + 20 + (i * (loc.w - 40)) / 7}
                    y1={loc.y + 6}
                    x2={loc.x + 12 + (i * (loc.w - 40)) / 7}
                    y2={loc.y + loc.h - 6}
                    stroke="#93c5fd"
                    strokeWidth="1"
                    opacity="0.35"
                  />
                ))}

              {isHover && loc.description && (
                <g>
                  <rect
                    x={loc.x}
                    y={loc.y + loc.h + 6}
                    width={Math.min(280, Math.max(140, loc.w + 60))}
                    height={26}
                    rx={6}
                    fill="#1f2937"
                    opacity={0.92}
                  />
                  <text x={loc.x + 8} y={loc.y + loc.h + 23} fontSize="11" fill="#f9fafb">
                    {loc.description.slice(0, 26)}
                  </text>
                </g>
              )}
            </g>
          );
        })}

        {/* 对话虚线 */}
        {dialogueLines.map((l) => (
          <line
            key={l.key}
            x1={l.x1}
            y1={l.y1}
            x2={l.x2}
            y2={l.y2}
            stroke="#0084ff"
            strokeWidth="1.5"
            strokeDasharray="4 4"
            opacity="0.55"
          />
        ))}

        {/* 角色 */}
        {locations.map((loc) =>
          (byLocation.get(loc.id) ?? []).map((c, i) => {
            const p = occupantPos(loc, (byLocation.get(loc.id) ?? []).length, i);
            return <CharacterDot key={c.id} c={c} x={p.x} y={p.y} onPick={onPickCharacter} />;
          }),
        )}
      </svg>

      {locations.length === 0 && (
        <div className="absolute inset-0 grid place-items-center text-sm text-muted">
          正在布置校园…
        </div>
      )}
    </div>
  );
}
