/**
 * 等距（2:1）投影与手绘素材配色。
 *
 * 坐标系统：地图对象全部用 **tile** 为单位（后端 `campus_map_objects`），
 * 这里负责 tile ↔ 屏幕 px 的换算，以及「简约 3D」三面体的几何构造。
 *
 *     screenX = originX + (tx - ty) * TILE_W / 2
 *     screenY =           (tx + ty) * TILE_H / 2
 *
 * 手绘感来自两处：① 边缘抖动（`wobblyEdge`，按对象 seed 稳定）；
 * ② 纹理点（草/波纹/石子，同样按 seed 稳定）。
 */

export const TILE_W = 64;
export const TILE_H = 32;
/** 建筑每 1 tile 高度对应的像素（立面拉伸量） */
export const WALL_UNIT = 22;
/** 地图外缘留白，避免边缘对象贴着画布 */
export const MAP_PAD = 90;

export interface Pt {
  x: number;
  y: number;
}

/** 投影原点：让 (0,0) 格落在正坐标区（最上方的菱角）。 */
export function originX(rows: number): number {
  return (rows * TILE_W) / 2;
}

export function toScreen(tx: number, ty: number, rows: number): Pt {
  return {
    x: originX(rows) + ((tx - ty) * TILE_W) / 2,
    y: ((tx + ty) * TILE_H) / 2,
  };
}

/** 屏幕 px → tile（编辑器拖动时用；与 toScreen 严格互逆）。 */
export function toTile(x: number, y: number, rows: number): { tx: number; ty: number } {
  const dx = x - originX(rows);
  const a = dx / (TILE_W / 2);
  const b = y / (TILE_H / 2);
  return { tx: (a + b) / 2, ty: (b - a) / 2 };
}

/** 地图整体尺寸（含建筑高度的向上余量）。 */
export function mapExtent(cols: number, rows: number, maxHeightTiles = 8): { width: number; height: number } {
  return {
    width: ((cols + rows) * TILE_W) / 2 + MAP_PAD * 2,
    height: ((cols + rows) * TILE_H) / 2 + MAP_PAD + maxHeightTiles * WALL_UNIT + 40,
  };
}

export function pathOf(points: Pt[]): string {
  if (points.length === 0) return '';
  return (
    points
      .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
      .join(' ') + ' Z'
  );
}

/** 等距矩形四角（顺序：北 → 东 → 南 → 西）。 */
export function quad(tx: number, ty: number, tw: number, th: number, rows: number): Pt[] {
  return [
    toScreen(tx, ty, rows),
    toScreen(tx + tw, ty, rows),
    toScreen(tx + tw, ty + th, rows),
    toScreen(tx, ty + th, rows),
  ];
}

/** 给一条边加稳定的手绘抖动，返回折线点（含首尾）。 */
export function wobblyEdge(a: Pt, b: Pt, seed: number, amp = 1.5, segs = 4): Pt[] {
  const rnd = seeded(seed);
  const out: Pt[] = [a];
  const nx = -(b.y - a.y);
  const ny = b.x - a.x;
  const len = Math.hypot(nx, ny) || 1;
  for (let i = 1; i < segs; i++) {
    const t = i / segs;
    const off = (rnd() - 0.5) * 2 * amp;
    out.push({
      x: a.x + (b.x - a.x) * t + (nx / len) * off,
      y: a.y + (b.y - a.y) * t + (ny / len) * off,
    });
  }
  out.push(b);
  return out;
}

export function polylinePath(points: Pt[]): string {
  if (points.length === 0) return '';
  return points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(' ');
}

/** 抖动后的多边形路径（用于地面块的手绘边缘）。 */
export function wobblyPolygon(points: Pt[], seed: number, amp = 1.5): string {
  const segs: Pt[] = [];
  for (let i = 0; i < points.length; i++) {
    const a = points[i];
    const b = points[(i + 1) % points.length];
    const edge = wobblyEdge(a, b, seed + i * 17, amp);
    segs.push(...edge.slice(0, -1));
  }
  return pathOf(segs);
}

/** 深度键（绘制顺序）：越靠近观察者（下）越大。 */
export function depthOf(tx: number, ty: number, tw = 1, th = 1): number {
  return tx + tw / 2 + (ty + th / 2);
}

/** 稳定伪随机：同一 seed 每次得到同一串数，保证纹理不闪烁。 */
export function seeded(seed: number): () => number {
  let s = (Math.floor(seed) || 1) % 233280;
  return () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/** 半格吸附（编辑器拖动）。 */
export function snap(v: number, step = 0.5): number {
  return Math.round(v / step) * step;
}

// ─────────────────────────── 配色（简约 3D，低饱和手绘感）───────────────────────────

export interface GroundStyle {
  fill: string;
  edge: string;
  texture: 'grass' | 'ripple' | 'pebble' | 'track' | 'tile' | 'grain';
  textureColor: string;
}

export const GROUND_STYLE: Record<string, GroundStyle> = {
  grass: { fill: '#cfe6c4', edge: '#b6d5a9', texture: 'grass', textureColor: '#a9cd97' },
  dirt: { fill: '#e3d3b6', edge: '#d3bf9c', texture: 'pebble', textureColor: '#c9b28c' },
  water: { fill: '#a9d8e6', edge: '#8dc6d9', texture: 'ripple', textureColor: '#d6f0f7' },
  field_track: { fill: '#d9b18c', edge: '#c39a75', texture: 'track', textureColor: '#f2f5f7' },
  plaza: { fill: '#e6e2da', edge: '#d2cdc2', texture: 'tile', textureColor: '#cfc9bd' },
  sand: { fill: '#f0e2c4', edge: '#e0cfa8', texture: 'grain', textureColor: '#e2d0aa' },
};

export interface BuildingStyle {
  roof: string;
  roofEdge: string;
  left: string;
  right: string;
  trim: string;
  /** 屋顶形状：flat 平顶 / gable 双坡 / dome 弧顶 */
  roofKind: 'flat' | 'gable' | 'dome';
}

export const BUILDING_STYLE: Record<string, BuildingStyle> = {
  main: { roof: '#e2a08c', roofEdge: '#cf8873', left: '#c9a692', right: '#dcbcaa', trim: '#f4ded4', roofKind: 'flat' },
  tower: { roof: '#9db8dc', roofEdge: '#7f9dc6', left: '#b7c3d6', right: '#cbd6e6', trim: '#e8eefa', roofKind: 'gable' },
  hall: { roof: '#c2a8d4', roofEdge: '#a98fbd', left: '#c6b7d2', right: '#d8cbe2', trim: '#f0e8f6', roofKind: 'flat' },
  canteen: { roof: '#e8bd8a', roofEdge: '#d4a470', left: '#d8c3a4', right: '#e7d5ba', trim: '#faeedd', roofKind: 'gable' },
  dorm: { roof: '#e6cf9b', roofEdge: '#d0b782', left: '#d6cbb2', right: '#e6dcc6', trim: '#f7f0e0', roofKind: 'flat' },
  shop: { roof: '#8fcbbd', roofEdge: '#72b3a4', left: '#b3d6cd', right: '#c8e3db', trim: '#e6f5f1', roofKind: 'flat' },
};

export const PROP_COLORS = {
  treeTrunk: '#b08462',
  treeLeaf: '#8fc98f',
  treeLeafAlt: '#a6d8a0',
  pineLeaf: '#7bb98a',
  pineLeafAlt: '#93c99f',
  rock: '#c3c8cf',
  rockAlt: '#d7dade',
  rockDark: '#a9b0b8',
  benchWood: '#c9a882',
  benchWoodTop: '#dcbe9a',
  benchLeg: '#a98962',
  lampPole: '#a8aab0',
  lampGlow: '#ffe9a8',
  flowerA: '#f2b8c6',
  flowerB: '#f6d68f',
  flowerC: '#c9b6e8',
  boardFace: '#f5efe2',
  boardFrame: '#c8ab86',
  avatarRing: '#94a3b8',
  playerRing: '#0084ff',
  meRing: '#f59e0b',
} as const;

/** 影子（等距椭圆）。 */
export function shadowEllipse(tx: number, ty: number, radius: number, rows: number): { cx: number; cy: number; rx: number; ry: number } {
  const p = toScreen(tx, ty, rows);
  return { cx: p.x, cy: p.y, rx: radius, ry: radius * 0.42 };
}
