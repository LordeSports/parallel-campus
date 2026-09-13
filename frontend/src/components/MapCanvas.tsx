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
      transform={`translate(${x} ${y})`}
      opacity={c.is_asleep ? 0.6 : 1}
      onClick={() => onPick(c.id)}
      style={{ cursor: 'pointer' }}
    >
      <circle r={r} fill="#ffffff" stroke={stroke} strokeWidth={c.is_me ? 3 : 2} />
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

  /** 地点 → 在场角色（按后端 occupants 顺序）。 */
  const byLocation = useMemo(() => {
    const map = new Map<string, CharacterSummaryView[]>();
    const index = new Map(Object.values(characters).map((c) => [c.id, c]));
    for (const loc of locations) {
      const ordered = (loc.occupants ?? [])
        .map((id) => index.get(id))
        .filter((c): c is CharacterSummaryView => Boolean(c));
      map.set(
        loc.id,
        ordered.length
          ? ordered
          : Object.values(characters).filter((c) => c.location_id === loc.id),
      );
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
        <rect x="0" y="0" width={VIEW_W} height={VIEW_H} fill="#f1f7f0" />
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
                fill="#ffffff"
                stroke={isActive ? '#0084ff' : '#dbe3ea'}
                strokeWidth={isActive ? 2.5 : 1.5}
                className={isActive ? 'animate-pulse-ring' : undefined}
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
