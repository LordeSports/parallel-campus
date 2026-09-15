/** 预览入口：造一张有代表性的校园地图 + 角色，把 IsoMap 渲成静态标记。 */
import { createElement } from 'react';

import IsoMap from '../src/components/IsoMap';
import type { CampusMapView, CharacterSummaryView, MapObjectView } from '../src/api/types';

let seq = 0;
const obj = (
  kind: MapObjectView['kind'],
  variant: string,
  tx: number,
  ty: number,
  tw: number,
  th: number,
  extra: Partial<MapObjectView> = {},
): MapObjectView => ({
  id: `mo_${seq++}`,
  kind,
  variant,
  tx,
  ty,
  tw,
  th,
  height: 0,
  layer: kind === 'ground' ? 0 : kind === 'prop' ? 10 : 20,
  name: '',
  location_id: null,
  props: { seed: (seq * 37) % 400 + 7 },
  ...extra,
});

const MAP: CampusMapView = {
  version: 1,
  cols: 40,
  rows: 30,
  title: '平行校园',
  objects: [
    // 地面
    obj('ground', 'grass', 0, 0, 40, 30, { props: { seed: 12 } }),
    obj('ground', 'plaza', 17, 13, 8, 6, { props: { seed: 41 } }),
    obj('ground', 'dirt', 22, 14, 12, 2.5, { props: { seed: 77 } }),
    obj('ground', 'water', 27, 2, 11, 8, { props: { seed: 5 } }),
    obj('ground', 'field_track', 2, 21, 11, 7, { props: { seed: 88 } }),
    obj('ground', 'sand', 15, 3, 6, 4, { props: { seed: 63 } }),

    // 建筑
    obj('building', 'tower', 5, 6, 6, 5, { height: 5.5, name: '图书馆', location_id: 'library' }),
    obj('building', 'main', 15, 6, 8, 6, { height: 4, name: '教学楼 A', location_id: 'teaching_a' }),
    obj('building', 'dorm', 28, 14, 8, 5, { height: 4, name: '宿舍楼', location_id: 'dorm' }),
    obj('building', 'canteen', 15, 17, 7, 5, { height: 3, name: '第一食堂', location_id: 'canteen' }),
    obj('building', 'hall', 2, 13, 6, 5, { height: 3, name: '活动室', location_id: 'club_room' }),
    obj('building', 'shop', 32, 23, 5, 4, { height: 2, name: '奶茶店', location_id: 'milktea' }),

    // 摆件
    obj('prop', 'tree', 12, 5, 1.4, 1.4, { props: { seed: 21 } }),
    obj('prop', 'tree', 13.6, 8.4, 1.4, 1.4, { props: { seed: 34 } }),
    obj('prop', 'tree', 26, 8, 1.4, 1.4, { props: { seed: 55 } }),
    obj('prop', 'tree', 37, 8, 1.4, 1.4, { props: { seed: 91 } }),
    obj('prop', 'tree', 4, 19, 1.4, 1.4, { props: { seed: 15 } }),
    obj('prop', 'pine', 26.4, 11.4, 1.4, 1.4, { props: { seed: 44 } }),
    obj('prop', 'pine', 24, 0.6, 1.4, 1.4, { props: { seed: 72 } }),
    obj('prop', 'pine', 10, 27, 1.4, 1.4, { props: { seed: 8 } }),
    obj('prop', 'lamp', 16, 12.6, 0.8, 0.8, { props: { seed: 19 } }),
    obj('prop', 'lamp', 25, 12.6, 0.8, 0.8, { props: { seed: 27 } }),
    obj('prop', 'lamp', 20.5, 19.6, 0.8, 0.8, { props: { seed: 61 } }),
    obj('prop', 'bench', 24, 11.6, 1.6, 0.7, { props: { seed: 33 } }),
    obj('prop', 'bench', 24.4, 4.5, 1.6, 0.7, { props: { seed: 47 } }),
    obj('prop', 'board', 19, 12.2, 1.6, 0.7, { props: { seed: 58 } }),
    obj('prop', 'flower', 17.5, 12.5, 1.2, 1.2, { props: { seed: 66 } }),
    obj('prop', 'flower', 23.5, 12.5, 1.2, 1.2, { props: { seed: 70 } }),
    obj('prop', 'rock', 30, 10, 1, 0.9, { props: { seed: 82 } }),
    obj('prop', 'rock', 31.5, 3.5, 1, 0.9, { props: { seed: 95 } }),
  ],
};


// 隔离测试：只放一栋楼，逐个 roofKind 看几何
const soloMap = (variant: string, height: number, tw: number, th: number): CampusMapView => ({
  version: 1,
  cols: 24,
  rows: 24,
  title: 'solo',
  objects: [
    obj('ground', 'grass', 0, 0, 24, 24, { props: { seed: 9 } }),
    obj('building', variant, 8, 8, tw, th, { height, name: '测试楼' }),
  ],
});

const CHARS: CharacterSummaryView[] = [
  { id: 'c1', kind: 'player', name: '林晚', avatar_key: 'av_03', location_id: 'library', is_me: true, mood: { valence: 0.4, arousal: 0.2 }, energy: 88 },
  { id: 'c2', kind: 'npc', name: '陈屿', avatar_key: 'av_07', location_id: 'library', mood: { valence: -0.1, arousal: 0.1 }, energy: 62 },
  { id: 'c3', kind: 'npc', name: '苏澈', avatar_key: 'av_11', location_id: 'teaching_a', mood: { valence: 0.2, arousal: 0.5 }, energy: 74 },
  { id: 'c4', kind: 'npc', name: '周予安', avatar_key: 'av_15', location_id: 'canteen', mood: { valence: 0.5, arousal: 0.3 } },
  { id: 'c5', kind: 'npc', name: '夏知', avatar_key: 'av_19', location_id: 'dorm', is_asleep: true, mood: { valence: -0.2 } },
  { id: 'c6', kind: 'npc', name: '何一鸣', avatar_key: 'av_22', location_id: 'club_room', mood: { valence: 0.1, arousal: -0.2 } },
];

function svgOnly(markup: string): string {
  const start = markup.indexOf('<svg');
  const end = markup.lastIndexOf('</svg>') + 6;
  const svg = markup.slice(start, end);
  return svg.replace(
    /^<svg /,
    '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="900" style="background:#f7f5ee" ',
  );
}

export function renderPreview(renderToStaticMarkup: (el: unknown) => string) {
  const view = { zoom: 1, panX: 0, panY: 0 };
  const sunny = renderToStaticMarkup(
    createElement(IsoMap, { map: MAP, characters: CHARS, weather: 'sunny', view, onViewChange: () => {} }),
  );
  const rainy = renderToStaticMarkup(
    createElement(IsoMap, { map: MAP, characters: CHARS, weather: 'rainy', view, onViewChange: () => {} }),
  );
  // 特写：放大 2.6 倍看屋顶/窗/门细节（图书馆在 (5,6)，教学楼在 (15,6)）
  const zoom = 2.6;
  const focus = (tx: number, ty: number) => {
    const originX = (MAP.rows * 64) / 2;
    const cx = originX + (tx - ty) * 32;
    const cy = ((tx + ty) * 32) / 2;
    return { zoom, panX: 640 - cx * zoom, panY: 420 - cy * zoom };
  };
  const detailLib = renderToStaticMarkup(
    createElement(IsoMap, { map: MAP, characters: CHARS, weather: 'sunny', view: focus(8, 8), onViewChange: () => {} }),
  );
  const detailTeach = renderToStaticMarkup(
    createElement(IsoMap, { map: MAP, characters: CHARS, weather: 'sunny', view: focus(19, 9), onViewChange: () => {} }),
  );
  const svg = svgOnly(sunny);
  const wrap = (body: string) => `<!doctype html><meta charset="utf-8"><style>body{margin:0}svg{display:block}</style>${body}`;
  const html = `<!doctype html><meta charset="utf-8"><title>校园地图预览</title>
<style>body{margin:0;background:#eceae3;font:14px/1.5 -apple-system,"Microsoft YaHei",sans-serif;padding:16px}
h1{font-size:15px;font-weight:500;margin:0 0 10px}h2{font-size:13px;font-weight:500;color:#555;margin:18px 0 6px}
svg{box-shadow:0 2px 14px rgba(0,0,0,.12);border-radius:10px;max-width:100%;height:auto}
</style><h1>平行校园 · 地图渲染预览</h1>
<h2>全景（晴）</h2>${svg}
<h2>特写 · 图书馆（弧顶/双坡 + 出檐）</h2>${svgOnly(detailLib).replace('width="1280" height="900"', 'width="1280" height="840"')}
<h2>特写 · 教学楼（平顶 + 窗带 + 门廊）</h2>${svgOnly(detailTeach).replace('width="1280" height="900"', 'width="1280" height="840"')}
<h2>雨</h2>${svgOnly(rainy)}`;
  // 24x24 地图里楼在 (8,8)-(14,13)，中心 tile (11,10.5)：x = 24*32 + (11-10.5)*32 = 784, y = 21.5*16 = 344
  const soloView = { zoom: 3.2, panX: 500 - 784 * 3.2, panY: 420 - 300 * 3.2 };
  const solo = (variant: string, height: number, tw: number, th: number) =>
    wrap(
      svgOnly(
        renderToStaticMarkup(
          createElement(IsoMap, {
            map: soloMap(variant, height, tw, th),
            weather: 'sunny',
            view: soloView,
            onViewChange: () => {},
          }),
        ),
      ),
    );
  return {
    svg,
    html,
    lib: wrap(svgOnly(detailLib)),
    teach: wrap(svgOnly(detailTeach)),
    soloTower: solo('tower', 5.5, 6, 5),
    soloMain: solo('main', 4, 7, 6),
    soloShop: solo('shop', 2, 5, 4),
  };
}
