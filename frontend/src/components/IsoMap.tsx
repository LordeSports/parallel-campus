/**
 * 等距校园地图渲染器（"简约 3D"手绘风）。
 *
 * - 地面块：等距矩形 + 抖动边缘 + 平铺纹理（草地/土路/水域/跑道/广场）
 * - 建筑：三面体（屋顶菱形 + 左右立面），按 variant 有平顶/双坡/弧顶
 * - 摆件：树、松、石块、长椅、路灯、花坛、公告板
 * - 角色：按 `location_id` 落到对应建筑门口
 *
 * 同一个组件服务两种场景：只读（玩家端）与可编辑（管理员编辑器）。
 * 编辑相关交互只在传入 `editable` 时挂载。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { CampusMapView, CharacterSummaryView, MapObjectView } from '../api/types';
import { avatarMeta } from '../avatar';
import { moodEmoji } from '../store/world';
import {
  BUILDING_STYLE,
  GROUND_STYLE,
  PROP_COLORS,
  TILE_H,
  TILE_W,
  WALL_UNIT,
  depthOf,
  mapExtent,
  pathOf,
  polylinePath,
  quad,
  seeded,
  toScreen,
  toTile,
  wobblyPolygon,
  type Pt,
} from '../map/iso';

export interface Viewport {
  zoom: number;
  panX: number;
  panY: number;
}

export interface IsoMapProps {
  map: CampusMapView | null;
  characters?: CharacterSummaryView[];
  editable?: boolean;
  selectedId?: string | null;
  /** 待放置素材：点击画布时在该处创建 */
  placing?: { kind: string; variant: string } | null;
  onSelect?: (id: string | null) => void;
  onPlace?: (tx: number, ty: number) => void;
  onMove?: (id: string, tx: number, ty: number) => void;
  onMoveEnd?: () => void;
  onPickCharacter?: (id: string) => void;
  showGrid?: boolean;
  view?: Viewport;
  onViewChange?: (v: Viewport) => void;
  className?: string;
}

const up = (p: Pt, dy: number): Pt => ({ x: p.x, y: p.y - dy });
const mid = (a: Pt, b: Pt): Pt => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
const GROUND_TEXTURE_ID: Record<string, string> = {
  grass: 'tex-grass',
  dirt: 'tex-pebble',
  water: 'tex-ripple',
  field_track: 'tex-track',
  plaza: 'tex-tile',
  sand: 'tex-grain',
};

// ─────────────────────────── 纹理 / 网格 ───────────────────────────

function Defs() {
  return (
    <defs>
      <pattern id="tex-grass" width="14" height="14" patternUnits="userSpaceOnUse">
        <path d="M3 9 q1.5 -3 3 0" fill="none" stroke="#a9cd97" strokeWidth="1.1" strokeLinecap="round" />
        <path d="M9 4 q1.5 -3 3 0" fill="none" stroke="#b9dba8" strokeWidth="1" strokeLinecap="round" />
      </pattern>
      <pattern id="tex-pebble" width="16" height="16" patternUnits="userSpaceOnUse">
        <circle cx="4" cy="5" r="1.5" fill="#c9b28c" opacity=".85" />
        <circle cx="11" cy="10" r="1.2" fill="#d8c4a2" opacity=".8" />
        <circle cx="7" cy="13" r="1" fill="#bfa77f" opacity=".7" />
      </pattern>
      <pattern id="tex-ripple" width="26" height="14" patternUnits="userSpaceOnUse">
        <path d="M0 7 q6 -3 13 0 q6 3 13 0" fill="none" stroke="#d6f0f7" strokeWidth="1.3" opacity=".9" />
        <path d="M0 12 q6 -3 13 0" fill="none" stroke="#bfe4f0" strokeWidth="1" opacity=".7" />
      </pattern>
      <pattern id="tex-tile" width="22" height="22" patternUnits="userSpaceOnUse">
        <path d="M0 0 L22 0 M0 0 L0 22" stroke="#cfc9bd" strokeWidth="1" opacity=".8" />
      </pattern>
      <pattern id="tex-track" width="30" height="30" patternUnits="userSpaceOnUse">
        <path d="M0 15 L30 15" stroke="#f2f5f7" strokeWidth="1.4" opacity=".5" />
      </pattern>
      <pattern id="tex-grain" width="12" height="12" patternUnits="userSpaceOnUse">
        <circle cx="3" cy="3" r="1" fill="#e2d0aa" />
        <circle cx="8" cy="9" r="1.2" fill="#ddc99f" />
      </pattern>
      <pattern id="tex-grid" width={TILE_W / 2} height={TILE_H / 2} patternUnits="userSpaceOnUse">
        <path
          d={`M0 0 L${TILE_W / 2} ${TILE_H / 4} L0 ${TILE_H / 2} L${-TILE_W / 2} ${TILE_H / 4} Z`}
          fill="none"
          stroke="#6b7280"
          strokeOpacity=".18"
          strokeWidth=".7"
        />
      </pattern>
      <filter id="iso-shadow" x="-30%" y="-30%" width="160%" height="180%">
        <feDropShadow dx="0" dy="6" stdDeviation="6" floodColor="#64748b" floodOpacity=".22" />
      </filter>
      <filter id="iso-sel" x="-40%" y="-40%" width="180%" height="180%">
        <feDropShadow dx="0" dy="0" stdDeviation="3" floodColor="#0084ff" floodOpacity=".9" />
      </filter>
    </defs>
  );
}

// ─────────────────────────── 地面 ───────────────────────────

function GroundBlock({ o, rows }: { o: MapObjectView; rows: number }) {
  const style = GROUND_STYLE[o.variant] ?? GROUND_STYLE.grass;
  const seed = Number(o.props?.seed ?? 7);
  const corners = quad(o.tx, o.ty, o.tw, o.th, rows);
  const shape = wobblyPolygon(corners, seed, o.tw > 12 ? 2.2 : 1.4);

  return (
    <g>
      <path d={shape} fill={style.fill} stroke={style.edge} strokeWidth="1.2" strokeLinejoin="round" />
      <path d={shape} fill={`url(#${GROUND_TEXTURE_ID[o.variant] ?? 'tex-grass'})`} opacity=".85" />
      {o.variant === 'field_track' && (
        <path
          d={pathOf([
            toScreen(o.tx + 0.7, o.ty + 0.7, rows),
            toScreen(o.tx + o.tw - 0.7, o.ty + 0.7, rows),
            toScreen(o.tx + o.tw - 0.7, o.ty + o.th - 0.7, rows),
            toScreen(o.tx + 0.7, o.ty + o.th - 0.7, rows),
          ])}
          fill="#cfe0b4"
          stroke="#f2f5f7"
          strokeWidth="3"
          strokeLinejoin="round"
        />
      )}
    </g>
  );
}

// ─────────────────────────── 建筑 ───────────────────────────

function BuildingShape({ o, rows }: { o: MapObjectView; rows: number }) {
  const st = BUILDING_STYLE[o.variant] ?? BUILDING_STYLE.main;
  const h = Math.max(0, o.height ?? 0) * WALL_UNIT;
  const seed = Number(o.props?.seed ?? 5);
  const [n, e, s, w] = quad(o.tx, o.ty, o.tw, o.th, rows);

  const nh = up(n, h);
  const eh = up(e, h);
  const sh = up(s, h);
  const wh = up(w, h);

  // 可见的两个立面：西南（w→s）与东南（s→e）
  const leftWall = pathOf([w, s, sh, wh]);
  const rightWall = pathOf([s, e, eh, sh]);
  // 侧面竖向纹理线（楼层感）
  const floorLines: string[] = [];
  const floors = Math.max(1, Math.round((o.height ?? 0)));
  for (let i = 1; i < floors; i++) {
    const dy = (h * i) / floors;
    floorLines.push(polylinePath([up(w, dy), up(s, dy)]));
    floorLines.push(polylinePath([up(s, dy), up(e, dy)]));
  }
  // 窗（沿两个立面均分）
  const windows: Pt[][] = [];
  const cols = Math.max(1, Math.round(o.tw / 1.6));
  for (let i = 0; i < cols; i++) {
    const t0 = (i + 0.3) / cols;
    const t1 = (i + 0.7) / cols;
    for (let f = 0; f < Math.max(1, floors - 1); f++) {
      const y0 = up({ x: 0, y: 0 }, (h * (f + 0.25)) / floors).y;
      const y1 = up({ x: 0, y: 0 }, (h * (f + 0.75)) / floors).y;
      windows.push([
        { x: w.x + (s.x - w.x) * t0, y: w.y + (s.y - w.y) * t0 + (y0 + 0) },
        { x: w.x + (s.x - w.x) * t1, y: w.y + (s.y - w.y) * t1 + y0 },
        { x: w.x + (s.x - w.x) * t1, y: w.y + (s.y - w.y) * t1 + y1 },
        { x: w.x + (s.x - w.x) * t0, y: w.y + (s.y - w.y) * t0 + y1 },
      ]);
    }
  }

  const rnd = seeded(seed);

  return (
    <g>
      {/* 影子 */}
      <path d={pathOf([n, e, s, w])} fill="#64748b" opacity=".16" transform="translate(3 5)" />
      {/* 立面 */}
      <path d={leftWall} fill={st.left} />
      <path d={rightWall} fill={st.right} />
      <path d={polylinePath([up(w, h), up(s, h), up(e, h)])} fill="none" stroke={st.trim} strokeWidth="2" opacity=".7" />
      {floorLines.map((d, i) => (
        <path key={`f${i}`} d={d} fill="none" stroke="#000" strokeOpacity=".06" strokeWidth="1" />
      ))}
      {windows.map((p, i) => (
        <path key={`w${i}`} d={pathOf(p)} fill="#e8f1fb" opacity={0.55 + rnd() * 0.25} stroke="#b9cfe4" strokeWidth=".6" />
      ))}
      {/* 屋顶 */}
      {st.roofKind === 'gable' ? (
        <>
          {(() => {
            const m1 = mid(n, e);
            const m2 = mid(w, s);
            const lift = h * 0.42;
            const m1h = up(m1, lift);
            const m2h = up(m2, lift);
            return (
              <>
                <path d={pathOf([n, m1, m1h, m2h, m2, w])} fill={st.roof} />
                <path d={pathOf([m1, e, s, m2, m2h, m1h])} fill={st.roofEdge} />
                <path d={polylinePath([wh, m2h, m1h, eh])} fill="none" stroke={st.trim} strokeWidth="2" opacity=".85" />
              </>
            );
          })()}
        </>
      ) : st.roofKind === 'dome' ? (
        <>
          <path d={pathOf([w, s, e, n])} fill={st.roofEdge} />
          <ellipse
            cx={mid(w, e).x}
            cy={up(mid(w, e), h * 0.5).y}
            rx={Math.abs(e.x - w.x) / 2.1}
            ry={TILE_H * 0.9}
            fill={st.roof}
          />
        </>
      ) : (
        <>
          <path d={pathOf([w, s, e, n])} fill={st.roof} />
          <path d={pathOf([wh, sh, eh, nh])} fill={st.roof} stroke={st.roofEdge} strokeWidth="1.4" />
          {/* 女儿墙 / 屋顶设备 */}
          <path
            d={pathOf([
              { x: wh.x + (sh.x - wh.x) * 0.3, y: wh.y + (sh.y - wh.y) * 0.3 - 6 },
              { x: nh.x + (eh.x - nh.x) * 0.55, y: nh.y + (eh.y - nh.y) * 0.55 - 6 },
              { x: nh.x + (eh.x - nh.x) * 0.55, y: nh.y + (eh.y - nh.y) * 0.55 - 1 },
              { x: wh.x + (sh.x - wh.x) * 0.3, y: wh.y + (sh.y - wh.y) * 0.3 - 1 },
            ])}
            fill="#ffffff"
            opacity=".38"
          />
        </>
      )}
    </g>
  );
}

// ─────────────────────────── 摆件 ───────────────────────────

function PropShape({ o, rows }: { o: MapObjectView; rows: number }) {
  const seed = Number(o.props?.seed ?? 3);
  const rnd = seeded(seed);
  const p = toScreen(o.tx + o.tw / 2, o.ty + o.th / 2, rows);
  const shadow = <ellipse cx={p.x + 2} cy={p.y + 3} rx={13 * (o.tw / 1.4)} ry={5} fill="#64748b" opacity=".16" />;

  switch (o.variant) {
    case 'tree':
      return (
        <g>
          {shadow}
          <rect x={p.x - 2.6} y={p.y - 12} width="5.2" height="13" rx="2.4" fill={PROP_COLORS.treeTrunk} />
          <circle cx={p.x} cy={p.y - 26} r="14.5" fill={PROP_COLORS.treeLeaf} />
          <circle cx={p.x + 8} cy={p.y - 32} r="10" fill={PROP_COLORS.treeLeafAlt} />
          <circle cx={p.x - 8} cy={p.y - 30} r="9" fill={PROP_COLORS.treeLeafAlt} opacity=".9" />
        </g>
      );
    case 'pine': {
      const h = 30 + rnd() * 8;
      return (
        <g>
          {shadow}
          <rect x={p.x - 2.4} y={p.y - 10} width="4.8" height="11" rx="2" fill={PROP_COLORS.treeTrunk} />
          <path d={pathOf([{ x: p.x, y: p.y - h - 14 }, { x: p.x + 12, y: p.y - h * 0.55 }, { x: p.x - 12, y: p.y - h * 0.55 }])} fill={PROP_COLORS.pineLeaf} />
          <path d={pathOf([{ x: p.x, y: p.y - h }, { x: p.x + 14, y: p.y - h * 0.3 }, { x: p.x - 14, y: p.y - h * 0.3 }])} fill={PROP_COLORS.pineLeafAlt} />
        </g>
      );
    }
    case 'rock':
      return (
        <g>
          {shadow}
          <path
            d={pathOf([
              { x: p.x - 9, y: p.y + 2 },
              { x: p.x - 6, y: p.y - 7 },
              { x: p.x + 1, y: p.y - 10 },
              { x: p.x + 8, y: p.y - 4 },
              { x: p.x + 9, y: p.y + 2 },
            ])}
            fill={PROP_COLORS.rock}
            stroke={PROP_COLORS.rockDark}
            strokeWidth="0.8"
          />
          <path d={pathOf([{ x: p.x - 6, y: p.y - 7 }, { x: p.x + 1, y: p.y - 10 }, { x: p.x + 2, y: p.y - 5 }])} fill={PROP_COLORS.rockAlt} opacity=".9" />
        </g>
      );
    case 'bench': {
      const w = o.tw * TILE_W * 0.42;
      const hh = 9;
      const a = { x: p.x - w / 2, y: p.y };
      const b = { x: p.x + w / 2, y: p.y - (w / 2) * (TILE_H / TILE_W) };
      const c = { x: p.x + w / 2, y: p.y + (w / 2) * (TILE_H / TILE_W) };
      const d = { x: p.x - w / 2, y: p.y };
      return (
        <g>
          <ellipse cx={p.x} cy={p.y + 4} rx={w * 0.55} ry={4.5} fill="#64748b" opacity=".16" />
          <path d={pathOf([a, b, c, d])} fill={PROP_COLORS.benchWoodTop} />
          <path d={pathOf([a, d, { x: d.x, y: d.y + hh }, { x: a.x, y: a.y + hh }])} fill={PROP_COLORS.benchWood} />
          <path d={pathOf([d, c, { x: c.x, y: c.y + hh }, { x: d.x, y: d.y + hh }])} fill={PROP_COLORS.benchLeg} opacity=".9" />
          <path d={polylinePath([{ x: b.x, y: b.y - 9 }, { x: c.x, y: c.y - 9 }, { x: d.x, y: d.y - 9 }])} fill="none" stroke={PROP_COLORS.benchWoodTop} strokeWidth="3" strokeLinecap="round" />
        </g>
      );
    }
    case 'lamp':
      return (
        <g>
          {shadow}
          <rect x={p.x - 1.6} y={p.y - 26} width="3.2" height="27" rx="1.6" fill={PROP_COLORS.lampPole} />
          <circle cx={p.x} cy={p.y - 29} r="7" fill={PROP_COLORS.lampGlow} opacity=".95" />
          <circle cx={p.x} cy={p.y - 29} r="4.5" fill="#fff8dc" />
        </g>
      );
    case 'flower': {
      const colors = [PROP_COLORS.flowerA, PROP_COLORS.flowerB, PROP_COLORS.flowerC];
      return (
        <g>
          {[...Array(6)].map((_, i) => {
            const a = (i / 6) * Math.PI * 2 + rnd();
            const rr = 5 + rnd() * 7;
            return <circle key={i} cx={p.x + Math.cos(a) * rr} cy={p.y + Math.sin(a) * rr * 0.5} r={2.6} fill={colors[i % 3]} />;
          })}
        </g>
      );
    }
    case 'board':
      return (
        <g>
          {shadow}
          <rect x={p.x - 13} y={p.y - 26} width="26" height="17" rx="2.5" fill={PROP_COLORS.boardFace} stroke={PROP_COLORS.boardFrame} strokeWidth="2" />
          <path d={polylinePath([{ x: p.x - 9, y: p.y - 21 }, { x: p.x + 9, y: p.y - 21 }])} stroke="#cfc7b6" strokeWidth="1.4" />
          <path d={polylinePath([{ x: p.x - 9, y: p.y - 17 }, { x: p.x + 4, y: p.y - 17 }])} stroke="#cfc7b6" strokeWidth="1.4" />
          <rect x={p.x - 12} y={p.y - 9} width="3" height="10" rx="1.4" fill={PROP_COLORS.boardFrame} />
          <rect x={p.x + 9} y={p.y - 9} width="3" height="10" rx="1.4" fill={PROP_COLORS.boardFrame} />
        </g>
      );
    default:
      return <g>{shadow}</g>;
  }
}

// ─────────────────────────── 角色 ───────────────────────────

function Character({ c, x, y, onPick }: { c: CharacterSummaryView; x: number; y: number; onPick?: (id: string) => void }) {
  const ring = c.is_me ? PROP_COLORS.meRing : c.kind === 'player' ? PROP_COLORS.playerRing : PROP_COLORS.avatarRing;
  // 头像走 av_XX 体系（未知 key 会稳定兜底），底色保证缺 emoji 字体时也能区分角色
  const meta = avatarMeta(c.avatar_key, c.id);
  const face = c.kind === 'system' ? '📣' : meta.emoji;
  // 角标只放情绪脸（arousal 传 null → 不带 ⚡，尺寸才放得下）
  const moodFace = moodEmoji(c.mood?.valence, null);
  return (
    <g
      transform={`translate(${x} ${y})`}
      opacity={c.is_asleep ? 0.6 : 1}
      onClick={onPick ? () => onPick(c.id) : undefined}
      style={{ cursor: onPick ? 'pointer' : 'default' }}
    >
      <ellipse cx="0" cy="3" rx="11" ry="4" fill="#64748b" opacity=".2" />
      <rect x="-5.5" y="-14" width="11" height="15" rx="5" fill={ring} opacity=".85" />
      <circle cx="0" cy="-20" r="9.5" fill={meta.bg} stroke={ring} strokeWidth={c.is_me ? 2.6 : 1.8} />
      <text textAnchor="middle" y="-16.5" fontSize="9.5" className="emoji" style={{ pointerEvents: 'none' }}>
        {face}
      </text>
      {/* 心情角标 */}
      <circle cx="8.5" cy="-28" r="5.2" fill="#fff" stroke="#e5e7eb" strokeWidth="0.8" />
      <text textAnchor="middle" x="8.5" y="-25" fontSize="6.5" className="emoji" style={{ pointerEvents: 'none' }}>
        {moodFace}
      </text>
      <text textAnchor="middle" y="14" fontSize="9.5" fill="#374151" style={{ pointerEvents: 'none' }}>
        {c.name.length > 5 ? `${c.name.slice(0, 5)}…` : c.name}
        {c.is_me ? '·我' : ''}
      </text>
      {c.is_asleep && (
        <text x="8" y="-30" fontSize="9" className="emoji" style={{ pointerEvents: 'none' }}>
          💤
        </text>
      )}
    </g>
  );
}

/** 角色站位：绑定该地点的最大对象前方空地，按行排布。 */
function spotFor(anchor: MapObjectView, index: number, rows: number): Pt {
  const perRow = Math.max(2, Math.floor(anchor.tw / 1.1));
  const col = index % perRow;
  const row = Math.floor(index / perRow);
  const tx = anchor.tx + 0.7 + col * 1.05;
  const ty = anchor.ty + anchor.th + 0.55 + row * 0.95;
  const p = toScreen(tx, ty, rows);
  return { x: p.x, y: p.y - 6 };
}

// ─────────────────────────── 主组件 ───────────────────────────

export default function IsoMap({
  map,
  characters = [],
  editable = false,
  selectedId = null,
  placing = null,
  onSelect,
  onPlace,
  onMove,
  onMoveEnd,
  onPickCharacter,
  showGrid = false,
  view,
  onViewChange,
  className,
}: IsoMapProps) {
  const rows = map?.rows ?? 30;
  const cols = map?.cols ?? 40;
  const objects = useMemo(() => map?.objects ?? [], [map?.objects]);
  const maxHeight = useMemo(
    () => objects.reduce((m, o) => Math.max(m, o.height ?? 0), 0),
    [objects],
  );
  const extent = useMemo(() => mapExtent(cols, rows, maxHeight), [cols, rows, maxHeight]);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const [drag, setDrag] = useState<{ id: string; grabTx: number; grabTy: number; objTx: number; objTy: number } | null>(null);
  const [panning, setPanning] = useState<{ clientX: number; clientY: number; panX: number; panY: number } | null>(null);
  /** 拖动超过阈值后抑制紧随的 click，避免平移地图时误点角色 */
  const suppressClick = useRef(false);

  // 视口：编辑器传入 view/onViewChange（受控）；玩家端只读时组件自管，
  // 这样「主显示区域无法放大」的问题在两种模式下都解决。
  const [innerView, setInnerView] = useState<Viewport>({ zoom: 1, panX: 0, panY: 0 });
  const controlled = Boolean(view && onViewChange);
  const vp: Viewport = controlled ? (view as Viewport) : innerView;
  const setVp = useCallback(
    (next: Viewport) => {
      if (controlled) onViewChange?.(next);
      else setInnerView(next);
    },
    [controlled, onViewChange],
  );
  const zoom = vp.zoom;
  const panX = vp.panX;
  const panY = vp.panY;

  /** client 坐标 → viewBox 坐标 → 世界坐标（未缩放） */
  const toWorld = useCallback((clientX: number, clientY: number): Pt | null => {
    const svg = svgRef.current;
    if (!svg) return null;
    const m = svg.getScreenCTM();
    if (!m) return null;
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const vb = pt.matrixTransform(m.inverse());
    return { x: (vb.x - panX) / zoom, y: (vb.y - panY) / zoom };
  }, [panX, panY, zoom]);

  /** 滚轮缩放：必须用原生监听才能 `preventDefault`（React 的 onWheel 是 passive）。 */
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheelNative = (e: WheelEvent) => {
      e.preventDefault();
      const world = toWorld(e.clientX, e.clientY);
      if (!world) return;
      const factor = e.deltaY > 0 ? 0.9 : 1.1;
      const nz = Math.max(0.3, Math.min(4, zoom * factor));
      // 以鼠标所在的世界点为中心缩放
      const screen = { x: world.x * zoom + panX, y: world.y * zoom + panY };
      setVp({ zoom: nz, panX: screen.x - world.x * nz, panY: screen.y - world.y * nz });
    };
    el.addEventListener('wheel', onWheelNative, { passive: false });
    return () => el.removeEventListener('wheel', onWheelNative);
  }, [panX, panY, setVp, toWorld, zoom]);

  const onObjectPointerDown = (e: React.PointerEvent, o: MapObjectView) => {
    if (!editable) return;
    e.stopPropagation();
    onSelect?.(o.id);
    if (placing) return;
    const world = toWorld(e.clientX, e.clientY);
    if (!world) return;
    const t = toTile(world.x, world.y, rows);
    setDrag({ id: o.id, grabTx: t.tx, grabTy: t.ty, objTx: o.tx, objTy: o.ty });
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };

  const onSvgPointerMove = (e: React.PointerEvent) => {
    if (drag && onMove) {
      const world = toWorld(e.clientX, e.clientY);
      if (!world) return;
      const t = toTile(world.x, world.y, rows);
      const nx = Math.round((drag.objTx + (t.tx - drag.grabTx)) * 2) / 2;
      const ny = Math.round((drag.objTy + (t.ty - drag.grabTy)) * 2) / 2;
      onMove(drag.id, nx, ny);
      return;
    }
    if (panning) {
      const dx = e.clientX - panning.clientX;
      const dy = e.clientY - panning.clientY;
      if (!suppressClick.current && Math.hypot(dx, dy) < 4) return; // 阈值内仍算点击
      suppressClick.current = true;
      setVp({ zoom, panX: panning.panX + dx, panY: panning.panY + dy });
    }
  };

  const endDrag = () => {
    if (drag) {
      setDrag(null);
      onMoveEnd?.();
    }
    setPanning(null);
  };

  const onSvgPointerDown = (e: React.PointerEvent) => {
    suppressClick.current = false;
    const world = toWorld(e.clientX, e.clientY);
    if (editable) {
      if (placing && world && onPlace) {
        const t = toTile(world.x, world.y, rows);
        onPlace(Math.round(t.tx * 2) / 2, Math.round(t.ty * 2) / 2);
        return;
      }
      // 空白处：取消选中
      onSelect?.(null);
    }
    // 两种模式都允许拖动平移（只读端也要能挪动查看）
    setPanning({ clientX: e.clientX, clientY: e.clientY, panX, panY });
  };

  /** 渲染顺序：先 layer 再 depth（等距下靠下/靠右的压在上层） */
  const ordered = useMemo(
    () => [...objects].sort((a, b) => {
      const la = a.layer ?? 0;
      const lb = b.layer ?? 0;
      if (la !== lb) return la - lb;
      return depthOf(a.tx, a.ty, a.tw, a.th) - depthOf(b.tx, b.ty, b.tw, b.th);
    }),
    [objects],
  );

  /** 角色：按 location_id 找到锚点对象 → 建筑/地块前方 */
  const charPlacements = useMemo(() => {
    const anchors = new Map<string, MapObjectView>();
    for (const o of objects) {
      const lid = o.location_id;
      if (!lid) continue;
      const prev = anchors.get(lid);
      if (!prev || o.tw * o.th > prev.tw * prev.th) anchors.set(lid, o);
    }
    const byLoc = new Map<string, CharacterSummaryView[]>();
    for (const c of characters) {
      if (c.kind === 'system') continue;
      const list = byLoc.get(c.location_id) ?? [];
      list.push(c);
      byLoc.set(c.location_id, list);
    }
    const out: { c: CharacterSummaryView; x: number; y: number }[] = [];
    for (const [locId, chars] of byLoc) {
      const anchor = anchors.get(locId);
      if (!anchor) continue;
      chars.forEach((c, i) => {
        const p = spotFor(anchor, i, rows);
        out.push({ c, x: p.x, y: p.y });
      });
    }
    return out;
  }, [characters, objects, rows]);

  if (!map) {
    return (
      <div className={`grid h-full w-full place-items-center text-sm text-muted ${className ?? ''}`}>
        正在展开校园地图…
      </div>
    );
  }

  return (
    <div className={`relative h-full w-full ${className ?? ''}`}>
      {/* 视图控制浮层：缩放 + 重置（原先主显示区无法放大） */}
      <div className="absolute right-3 top-3 z-10 flex items-center gap-1 rounded-xl bg-white/85 px-1.5 py-1 shadow-sm backdrop-blur">
        <button
          type="button"
          className="h-7 w-7 rounded-lg text-sm text-ink hover:bg-black/5"
          title="缩小"
          onClick={() => setVp({ ...vp, zoom: Math.max(0.3, zoom / 1.2) })}
        >
          −
        </button>
        <span className="min-w-[42px] text-center text-[11px] tabular-nums text-muted">
          {Math.round(zoom * 100)}%
        </span>
        <button
          type="button"
          className="h-7 w-7 rounded-lg text-sm text-ink hover:bg-black/5"
          title="放大"
          onClick={() => setVp({ ...vp, zoom: Math.min(4, zoom * 1.2) })}
        >
          ＋
        </button>
        <button
          type="button"
          className="ml-0.5 rounded-lg px-2 py-1 text-[11px] text-muted hover:bg-black/5"
          title="适应视图"
          onClick={() => setVp({ zoom: 1, panX: 0, panY: 0 })}
        >
          重置
        </button>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${extent.width} ${extent.height}`}
        preserveAspectRatio="xMidYMid meet"
        className={`h-full w-full ${editable ? 'cursor-grab' : ''}`}
        onPointerDown={onSvgPointerDown}
        onPointerMove={onSvgPointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
        onClickCapture={(e) => {
          if (suppressClick.current) {
            e.stopPropagation();
            suppressClick.current = false;
          }
        }}
        style={{ touchAction: 'none' }}
      >
      <Defs />

      {/* 地面底色 */}
      <rect x="0" y="0" width={extent.width} height={extent.height} fill="#f4f1e8" />

      <g transform={`translate(${panX} ${panY}) scale(${zoom})`}>
        {/* 坐标网格 */}
        {showGrid && (
          <path
            d={pathOf([
              toScreen(0, 0, rows),
              toScreen(cols, 0, rows),
              toScreen(cols, rows, rows),
              toScreen(0, rows, rows),
            ])}
            fill="url(#tex-grid)"
          />
        )}

        {ordered.map((o) => {
          const isSel = selectedId === o.id;
          return (
            <g
              key={o.id}
              onPointerDown={(e) => onObjectPointerDown(e, o)}
              style={{ cursor: editable ? 'move' : 'default' }}
              filter={isSel ? 'url(#iso-sel)' : undefined}
            >
              {o.kind === 'ground' && <GroundBlock o={o} rows={rows} />}
              {o.kind === 'building' && <BuildingShape o={o} rows={rows} />}
              {o.kind === 'prop' && <PropShape o={o} rows={rows} />}
              {isSel && (
                <path
                  d={pathOf(quad(o.tx, o.ty, o.tw, o.th, rows))}
                  fill="#0084ff"
                  fillOpacity=".12"
                  stroke="#0084ff"
                  strokeWidth="1.6"
                  strokeDasharray="5 4"
                />
              )}
            </g>
          );
        })}

        {/* 角色 */}
        {charPlacements.map(({ c, x, y }) => (
          <Character key={c.id} c={c} x={x} y={y} onPick={onPickCharacter} />
        ))}
      </g>

      {/* 放置模式提示 */}
      {editable && placing && (
        <text x={extent.width / 2} y={extent.height - 14} textAnchor="middle" fontSize="13" fill="#0084ff">
          点击地图空白处放置「{placing.variant}」· Esc 取消
        </text>
      )}
      </svg>
    </div>
  );
}
